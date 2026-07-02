"""Tests unitaires pour le cas d'usage `InscrireClient` (#8).

Tous les ports sont remplacés par des fakes (conftest.py) : pas de base de
données, pas de hachage réel, pas de SMS. On vérifie ici l'orchestration
applicative, les garde-fous de sécurité (clair jamais persisté) et le
comportement sur doublon — y compris le fallback `IntegrityError` concurrente.
"""

from __future__ import annotations

import datetime
from random import Random

import pytest

from coiflink_api.application.inscription import CommandeInscription, InscrireClient
from coiflink_api.domaine.enums import Role, UserStatus
from coiflink_api.domaine.erreurs import (
    MotDePasseInvalide,
    NomInvalide,
    TelephoneDejaUtilise,
    TelephoneInvalide,
)

from .conftest import (
    FakeDepotOtp,
    FakeDepotUtilisateur,
    FakeDepotUtilisateurLeveDublon,
    FakeExpediteurOtp,
    FakeHacheur,
)

_MAINTENANT = datetime.datetime(2026, 1, 1, 12, 0, 0, tzinfo=datetime.timezone.utc)
_RNG_FIXE = Random(42)

_COMMANDE_VALIDE = CommandeInscription(
    full_name="Awa Koné",
    telephone="0700000000",
    mot_de_passe="motdepasse-solide",
    email=None,
)


def _creer_usecase(
    depot: FakeDepotUtilisateur | FakeDepotUtilisateurLeveDublon | None = None,
    hacheur: FakeHacheur | None = None,
    otp_active: bool = False,
    expediteur: FakeExpediteurOtp | None = None,
    depot_otp: FakeDepotOtp | None = None,
) -> InscrireClient:
    return InscrireClient(
        depot=depot or FakeDepotUtilisateur(),
        hacheur=hacheur or FakeHacheur(),
        otp_active=otp_active,
        expediteur_otp=expediteur,
        depot_otp=depot_otp,
        rng=Random(42),
        horloge=lambda: _MAINTENANT,
    )


class TestInscriptionReussie:
    def test_retourne_utilisateur_avec_role_client(self) -> None:
        uc = _creer_usecase()
        utilisateur = uc.executer(_COMMANDE_VALIDE)
        assert utilisateur.role == Role.CLIENT.value

    def test_retourne_utilisateur_avec_statut_active(self) -> None:
        uc = _creer_usecase()
        utilisateur = uc.executer(_COMMANDE_VALIDE)
        assert utilisateur.status == UserStatus.ACTIVE.value

    def test_retourne_nom_normalise(self) -> None:
        uc = _creer_usecase()
        commande = CommandeInscription(
            full_name="  Awa Koné  ",
            telephone="0700000000",
            mot_de_passe="motdepasse-solide",
        )
        utilisateur = uc.executer(commande)
        assert utilisateur.full_name == "Awa Koné"

    def test_retourne_telephone_canonique(self) -> None:
        uc = _creer_usecase()
        utilisateur = uc.executer(_COMMANDE_VALIDE)
        # 0700000000 doit être normalisé en E.164
        assert utilisateur.telephone == "+2250700000000"

    def test_email_none_si_non_fourni(self) -> None:
        uc = _creer_usecase()
        utilisateur = uc.executer(_COMMANDE_VALIDE)
        assert utilisateur.email is None

    def test_email_transmis_si_fourni(self) -> None:
        uc = _creer_usecase()
        commande = CommandeInscription(
            full_name="Awa Koné",
            telephone="0700000000",
            mot_de_passe="motdepasse-solide",
            email="awa@example.com",
        )
        utilisateur = uc.executer(commande)
        assert utilisateur.email == "awa@example.com"

    def test_utilisateur_ne_contient_pas_de_secret(self) -> None:
        uc = _creer_usecase()
        utilisateur = uc.executer(_COMMANDE_VALIDE)
        # L'entité retournée ne doit exposer ni le clair ni le condensat
        assert not hasattr(utilisateur, "mot_de_passe")
        assert not hasattr(utilisateur, "password")
        assert not hasattr(utilisateur, "password_hash")


class TestMotDePasseNonPersiste:
    def test_depot_recoit_condensat_pas_le_clair(self) -> None:
        depot = FakeDepotUtilisateur()
        hacheur = FakeHacheur()
        mdp_clair = "motdepasse-solide"
        uc = _creer_usecase(depot=depot, hacheur=hacheur)
        uc.executer(_COMMANDE_VALIDE)

        assert len(depot.crees) == 1
        assert depot.crees[0].password_hash != mdp_clair
        assert depot.crees[0].password_hash == hacheur.hacher(mdp_clair)

    def test_depot_ne_stocke_jamais_le_mot_de_passe_en_clair(self) -> None:
        depot = FakeDepotUtilisateur()
        mdp_clair = "motdepasse-solide"
        uc = _creer_usecase(depot=depot)
        uc.executer(_COMMANDE_VALIDE)

        assert depot.crees[0].password_hash != mdp_clair


class TestDoublonTelephone:
    def test_doublon_via_precheck_leve_telephone_deja_utilise(self) -> None:
        # Téléphone déjà normalisé dans le dépôt
        depot = FakeDepotUtilisateur(telephones_existants={"+2250700000000"})
        uc = _creer_usecase(depot=depot)
        with pytest.raises(TelephoneDejaUtilise):
            uc.executer(_COMMANDE_VALIDE)

    def test_doublon_via_fallback_integrity_error_leve_telephone_deja_utilise(self) -> None:
        """Simule un depot.creer() levant TelephoneDejaUtilise (race condition)."""
        depot = FakeDepotUtilisateurLeveDublon()
        uc = _creer_usecase(depot=depot)
        with pytest.raises(TelephoneDejaUtilise):
            uc.executer(_COMMANDE_VALIDE)

    def test_0_local_et_e164_detects_comme_meme_doublon(self) -> None:
        """0700000000 et +2250700000000 produisent la même forme E.164 → doublon détecté."""
        depot = FakeDepotUtilisateur(telephones_existants={"+2250700000000"})
        uc = _creer_usecase(depot=depot)
        commande_locale = CommandeInscription(
            full_name="Autre",
            telephone="0700000000",  # format local
            mot_de_passe="motdepasse-solide",
        )
        with pytest.raises(TelephoneDejaUtilise):
            uc.executer(commande_locale)


class TestValidationEntrees:
    def test_nom_vide_leve_nom_invalide(self) -> None:
        uc = _creer_usecase()
        with pytest.raises(NomInvalide):
            uc.executer(
                CommandeInscription(full_name="", telephone="0700000000", mot_de_passe="motdepasse-ok")
            )

    def test_nom_espaces_seuls_leve_nom_invalide(self) -> None:
        uc = _creer_usecase()
        with pytest.raises(NomInvalide):
            uc.executer(
                CommandeInscription(full_name="   ", telephone="0700000000", mot_de_passe="motdepasse-ok")
            )

    def test_mot_de_passe_trop_court_leve_mot_de_passe_invalide(self) -> None:
        uc = _creer_usecase()
        with pytest.raises(MotDePasseInvalide):
            uc.executer(
                CommandeInscription(full_name="Awa", telephone="0700000000", mot_de_passe="court")
            )

    def test_telephone_invalide_leve_telephone_invalide(self) -> None:
        uc = _creer_usecase()
        with pytest.raises(TelephoneInvalide):
            uc.executer(
                CommandeInscription(full_name="Awa", telephone="abc", mot_de_passe="motdepasse-ok")
            )

    def test_telephone_vide_leve_telephone_invalide(self) -> None:
        uc = _creer_usecase()
        with pytest.raises(TelephoneInvalide):
            uc.executer(
                CommandeInscription(full_name="Awa", telephone="", mot_de_passe="motdepasse-ok")
            )


class TestEmailNormalisation:
    def test_email_vide_stocke_comme_none(self) -> None:
        """email='' est falsy → l'inscription le stocke comme None."""
        uc = _creer_usecase()
        commande = CommandeInscription(
            full_name="Awa Koné",
            telephone="0700000000",
            mot_de_passe="motdepasse-solide",
            email="",
        )
        utilisateur = uc.executer(commande)
        assert utilisateur.email is None


class TestSecuriteMessageDoublon:
    def test_doublon_message_ne_contient_pas_le_telephone(self) -> None:
        """TelephoneDejaUtilise ne doit pas fuiter le numéro (PRD §11.1)."""
        telephone = "0700000000"
        depot = FakeDepotUtilisateur(telephones_existants={"+2250700000000"})
        uc = _creer_usecase(depot=depot)
        try:
            uc.executer(
                CommandeInscription(
                    full_name="Awa Koné",
                    telephone=telephone,
                    mot_de_passe="motdepasse-solide",
                )
            )
        except Exception as exc:  # noqa: BLE001
            assert telephone not in str(exc)
            assert "+2250700000000" not in str(exc)


class TestOtp:
    def test_otp_non_emis_si_desactive(self) -> None:
        expediteur = FakeExpediteurOtp()
        uc = _creer_usecase(otp_active=False, expediteur=expediteur)
        uc.executer(_COMMANDE_VALIDE)
        assert expediteur.envois == []

    def test_otp_emis_si_active(self) -> None:
        expediteur = FakeExpediteurOtp()
        uc = _creer_usecase(otp_active=True, expediteur=expediteur)
        uc.executer(_COMMANDE_VALIDE)
        assert len(expediteur.envois) == 1

    def test_otp_envoye_au_bon_telephone(self) -> None:
        expediteur = FakeExpediteurOtp()
        uc = _creer_usecase(otp_active=True, expediteur=expediteur)
        uc.executer(_COMMANDE_VALIDE)
        telephone_envoye, _ = expediteur.envois[0]
        assert telephone_envoye == "+2250700000000"

    def test_otp_enregistre_dans_depot_si_active(self) -> None:
        depot_otp = FakeDepotOtp()
        uc = _creer_usecase(otp_active=True, depot_otp=depot_otp)
        uc.executer(_COMMANDE_VALIDE)
        assert depot_otp.recuperer("+2250700000000") is not None

    def test_otp_non_enregistre_si_desactive(self) -> None:
        depot_otp = FakeDepotOtp()
        uc = _creer_usecase(otp_active=False, depot_otp=depot_otp)
        uc.executer(_COMMANDE_VALIDE)
        assert depot_otp.recuperer("+2250700000000") is None

    def test_utilisateur_retourne_ne_contient_pas_otp(self) -> None:
        expediteur = FakeExpediteurOtp()
        uc = _creer_usecase(otp_active=True, expediteur=expediteur)
        utilisateur = uc.executer(_COMMANDE_VALIDE)
        assert not hasattr(utilisateur, "otp")
        assert not hasattr(utilisateur, "code_otp")


class TestOtpParametresPersonnalises:
    def test_longueur_otp_personnalisee_appliquee(self) -> None:
        """longueur_otp=4 → le défi stocké a un code de 4 chiffres."""
        depot_otp = FakeDepotOtp()
        uc = InscrireClient(
            depot=FakeDepotUtilisateur(),
            hacheur=FakeHacheur(),
            otp_active=True,
            depot_otp=depot_otp,
            rng=Random(42),
            horloge=lambda: _MAINTENANT,
            longueur_otp=4,
        )
        uc.executer(_COMMANDE_VALIDE)
        defi = depot_otp.recuperer("+2250700000000")
        assert defi is not None
        assert len(defi.code) == 4

    def test_ttl_otp_personnalise_applique(self) -> None:
        """ttl_otp custom → expire_a = maintenant + ttl_custom."""
        depot_otp = FakeDepotOtp()
        ttl_custom = datetime.timedelta(minutes=10)
        uc = InscrireClient(
            depot=FakeDepotUtilisateur(),
            hacheur=FakeHacheur(),
            otp_active=True,
            depot_otp=depot_otp,
            rng=Random(42),
            horloge=lambda: _MAINTENANT,
            ttl_otp=ttl_custom,
        )
        uc.executer(_COMMANDE_VALIDE)
        defi = depot_otp.recuperer("+2250700000000")
        assert defi is not None
        assert defi.expire_a == _MAINTENANT + ttl_custom

    def test_max_essais_otp_personnalise_applique(self) -> None:
        """max_essais_otp=5 → essais_restants == 5 dans le défi."""
        depot_otp = FakeDepotOtp()
        uc = InscrireClient(
            depot=FakeDepotUtilisateur(),
            hacheur=FakeHacheur(),
            otp_active=True,
            depot_otp=depot_otp,
            rng=Random(42),
            horloge=lambda: _MAINTENANT,
            max_essais_otp=5,
        )
        uc.executer(_COMMANDE_VALIDE)
        defi = depot_otp.recuperer("+2250700000000")
        assert defi is not None
        assert defi.essais_restants == 5


class TestOtpSansInfrastructureComplete:
    def test_otp_active_sans_depot_otp_ne_plante_pas(self) -> None:
        """Seul l'expéditeur est fourni : l'inscription doit quand même réussir."""
        expediteur = FakeExpediteurOtp()
        uc = InscrireClient(
            depot=FakeDepotUtilisateur(),
            hacheur=FakeHacheur(),
            otp_active=True,
            expediteur_otp=expediteur,
            depot_otp=None,
            rng=Random(42),
            horloge=lambda: _MAINTENANT,
        )
        uc.executer(_COMMANDE_VALIDE)
        assert len(expediteur.envois) == 1

    def test_otp_active_sans_expediteur_ne_plante_pas(self) -> None:
        """Seul le dépôt OTP est fourni : l'inscription doit quand même réussir."""
        depot_otp = FakeDepotOtp()
        uc = InscrireClient(
            depot=FakeDepotUtilisateur(),
            hacheur=FakeHacheur(),
            otp_active=True,
            expediteur_otp=None,
            depot_otp=depot_otp,
            rng=Random(42),
            horloge=lambda: _MAINTENANT,
        )
        uc.executer(_COMMANDE_VALIDE)
        assert depot_otp.recuperer("+2250700000000") is not None

    def test_otp_active_sans_depot_ni_expediteur_ne_plante_pas(self) -> None:
        """Ni dépôt ni expéditeur : l'OTP est généré en mémoire sans effet de bord."""
        uc = InscrireClient(
            depot=FakeDepotUtilisateur(),
            hacheur=FakeHacheur(),
            otp_active=True,
            expediteur_otp=None,
            depot_otp=None,
            rng=Random(42),
            horloge=lambda: _MAINTENANT,
        )
        utilisateur = uc.executer(_COMMANDE_VALIDE)
        assert utilisateur is not None
