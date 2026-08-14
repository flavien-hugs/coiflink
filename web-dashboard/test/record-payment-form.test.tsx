// Test d'interaction — `RecordPaymentForm` (US-5.1, #33 ; Mobile Money #170).
// Nécessite `@testing-library/react` + jsdom (même patron que
// `receipt-print-modal.test.tsx`) : le champ téléphone Mobile Money n'apparaît
// qu'après un clic sur le sélecteur de mode, impossible à exercer via un rendu
// statique. Couvre : champ téléphone masqué hors Mobile Money, apparition +
// pré-remplissage au passage sur Mobile Money (depuis `defaultMobileMoneyPhone`,
// jamais écrasé si déjà saisi), libellé « Référence » devenant obligatoire pour
// ce mode, blocage côté client (téléphone/référence absents) sans appel réseau,
// et le corps posté au BFF quand tout est valide.

import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/navigation", () => ({
  useRouter: vi.fn(() => ({ refresh: vi.fn() })),
}));

import { RecordPaymentForm } from "../src/adapters/ui/record-payment-form";

const SALON_ID = "salon-uuid-record-payment";
const TICKET_ID = "ticket-uuid-record-payment";

function stubFetchOnce(status: number, body: unknown): ReturnType<typeof vi.fn> {
  const mock = vi.fn().mockResolvedValue({ status, json: async () => body });
  vi.stubGlobal("fetch", mock);
  return mock;
}

beforeEach(() => {
  vi.stubGlobal("fetch", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("RecordPaymentForm — champ téléphone Mobile Money", () => {
  it("masqué par défaut (mode CASH)", () => {
    render(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
      />,
    );
    expect(screen.queryByPlaceholderText("0700000000")).not.toBeInTheDocument();
  });

  it("apparaît et se pré-remplit au passage sur Mobile Money", () => {
    render(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
        defaultMobileMoneyPhone="+2250700000000"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Mobile Money (manuel)" }));

    const phoneInput = screen.getByPlaceholderText("0700000000") as HTMLInputElement;
    expect(phoneInput.value).toBe("+2250700000000");
  });

  it("repasse masqué en revenant sur un autre mode", () => {
    render(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
        defaultMobileMoneyPhone="+2250700000000"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Mobile Money (manuel)" }));
    expect(screen.getByPlaceholderText("0700000000")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Espèces" }));
    expect(screen.queryByPlaceholderText("0700000000")).not.toBeInTheDocument();
  });

  it("ne pré-remplit pas par-dessus un téléphone déjà saisi manuellement", () => {
    render(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
        defaultMobileMoneyPhone="+2250700000000"
      />,
    );

    // Bascule vers Mobile Money, corrige le téléphone, repasse en Espèces puis
    // revient sur Mobile Money : la correction manuelle doit survivre.
    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Mobile Money (manuel)" }));
    const phoneInput = screen.getByPlaceholderText("0700000000") as HTMLInputElement;
    fireEvent.change(phoneInput, { target: { value: "+2250711111111" } });

    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Espèces" }));
    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Mobile Money (manuel)" }));

    expect(
      (screen.getByPlaceholderText("0700000000") as HTMLInputElement).value,
    ).toBe("+2250711111111");
  });

  it("sans téléphone client par défaut, le champ démarre vide", () => {
    render(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
        defaultMobileMoneyPhone={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Mobile Money (manuel)" }));

    expect((screen.getByPlaceholderText("0700000000") as HTMLInputElement).value).toBe("");
  });

  it("se resynchronise si la fiche client résout APRÈS avoir déjà sélectionné Mobile Money", () => {
    // La fiche client (donc `defaultMobileMoneyPhone`) se résout de façon
    // asynchrone côté appelant (`PaymentDrawer`) : si le gérant sélectionne
    // Mobile Money avant que ce fetch aboutisse, le champ ne doit pas rester
    // bloqué vide indéfiniment une fois la vraie valeur disponible.
    const { rerender } = render(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
        defaultMobileMoneyPhone={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Mobile Money (manuel)" }));
    expect((screen.getByPlaceholderText("0700000000") as HTMLInputElement).value).toBe("");

    // Le fetch de la fiche client résout : le composant parent re-rend avec
    // la prop mise à jour, sans que `RecordPaymentForm` soit remonté.
    rerender(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
        defaultMobileMoneyPhone="+2250700000000"
      />,
    );

    expect((screen.getByPlaceholderText("0700000000") as HTMLInputElement).value).toBe(
      "+2250700000000",
    );
  });

  it("la résolution tardive de la fiche client n'écrase jamais une saisie manuelle déjà en cours", () => {
    const { rerender } = render(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
        defaultMobileMoneyPhone={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Mobile Money (manuel)" }));
    fireEvent.change(screen.getByPlaceholderText("0700000000"), {
      target: { value: "+2250799999999" },
    });

    rerender(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
        defaultMobileMoneyPhone="+2250700000000"
      />,
    );

    expect((screen.getByPlaceholderText("0700000000") as HTMLInputElement).value).toBe(
      "+2250799999999",
    );
  });
});

describe("RecordPaymentForm — libellé Référence dynamique", () => {
  it("« Référence » est optionnelle hors Mobile Money, obligatoire pour ce mode", () => {
    render(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
      />,
    );

    expect(screen.getByText("(Optionnel)")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Mobile Money (manuel)" }));

    expect(screen.queryByText("(Optionnel)")).not.toBeInTheDocument();
  });
});

describe("RecordPaymentForm — blocage côté client (Mobile Money)", () => {
  it("téléphone absent → erreur affichée, aucun appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
        defaultMobileMoneyPhone={null}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Mobile Money (manuel)" }));
    fireEvent.change(screen.getByPlaceholderText("Numéro de transaction Mobile Money"), {
      target: { value: "MM-TX-0001" },
    });
    fireEvent.click(screen.getByRole("button", { name: /enregistrer le paiement/i }));

    expect(
      await screen.findByText("Le numéro de téléphone Mobile Money est requis."),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("référence absente → erreur affichée, aucun appel réseau", async () => {
    const fetchMock = vi.fn();
    vi.stubGlobal("fetch", fetchMock);

    render(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
        defaultMobileMoneyPhone="+2250700000000"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Mobile Money (manuel)" }));
    fireEvent.click(screen.getByRole("button", { name: /enregistrer le paiement/i }));

    expect(
      await screen.findByText("Le numéro de transaction Mobile Money est requis."),
    ).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });
});

describe("RecordPaymentForm — soumission Mobile Money valide", () => {
  it("poste le téléphone et la référence au BFF", async () => {
    const fetchMock = stubFetchOnce(201, { id: "payment-uuid" });

    render(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
        defaultMobileMoneyPhone="+2250700000000"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Mobile Money (manuel)" }));
    fireEvent.change(screen.getByPlaceholderText("Numéro de transaction Mobile Money"), {
      target: { value: "MM-TX-0001" },
    });
    fireEvent.click(screen.getByRole("button", { name: /enregistrer le paiement/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.paymentMethod).toBe("MOBILE_MONEY_MANUAL");
    expect(body.mobileMoneyPhone).toBe("+2250700000000");
    expect(body.reference).toBe("MM-TX-0001");
  });

  it("un téléphone saisi sous Mobile Money puis abandonné (retour à Espèces) n'est jamais posté", async () => {
    const fetchMock = stubFetchOnce(201, { id: "payment-uuid" });

    render(
      <RecordPaymentForm
        salonId={SALON_ID}
        services={[]}
        queueTicketId={TICKET_ID}
        expectedAmount="5000.00"
        defaultMobileMoneyPhone="+2250700000000"
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Mobile Money (manuel)" }));
    // Le téléphone est déjà pré-rempli ; on bascule vers Espèces avant de
    // soumettre — le téléphone tapé ne doit jamais atteindre le BFF.
    fireEvent.click(screen.getByRole("button", { name: /mode de paiement/i }));
    fireEvent.click(screen.getByRole("option", { name: "Espèces" }));
    fireEvent.click(screen.getByRole("button", { name: /enregistrer le paiement/i }));

    await waitFor(() => expect(fetchMock).toHaveBeenCalledTimes(1));
    const [, init] = fetchMock.mock.calls[0] as [string, RequestInit];
    const body = JSON.parse(init.body as string) as Record<string, unknown>;
    expect(body.paymentMethod).toBe("CASH");
    expect(body.mobileMoneyPhone).toBeNull();
  });
});
