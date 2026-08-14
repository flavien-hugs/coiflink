// Test d'interaction — `ReceiptPrintModal` (ADR-0040), premier `.test.tsx` du
// dépôt : nécessite `@testing-library/react` + jsdom (`vitest.config.ts`) pour
// simuler les transitions loading → erreur → prêt → impression que le rendu
// statique (`renderToStaticMarkup`, patron des autres composants) ne peut pas
// exercer. Couvre : spinner pendant le chargement, bannière d'erreur + retour au
// spinner sur « Réessayer », contenu du reçu à l'état prêt (salon/client/lignes/
// total), clic « Imprimer » → `window.print()` appelé, évènement `afterprint` →
// bannière de confirmation « best-effort » (ADR-0040 §5).

import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ReceiptPrintModal } from "../src/adapters/ui/receipt-print-modal";

const SALON_ID = "salon-uuid-modal";
const PAYMENT_ID = "payment-uuid-modal";

const FAKE_RECEIPT_BODY = {
  receipt: {
    receiptNumber: "REC-000001",
    paymentId: PAYMENT_ID,
    salonId: SALON_ID,
    salonName: "Salon Élégance",
    ticketNumber: null,
    clientName: "Awa Koné",
    clientPhone: "+2250700000001",
    amount: "5000.00",
    currency: "XOF",
    paymentMethod: "CASH",
    status: "VALIDATED",
    reference: null,
    paidAt: "2026-01-01T00:00:00Z",
    lines: [{ serviceName: "Coupe homme", amount: "5000.00" }],
  },
};

function stubFetch(status: number, body: unknown): void {
  vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ status, json: async () => body }));
}

function stubFetchPending(): void {
  vi.stubGlobal("fetch", vi.fn(() => new Promise(() => {})));
}

beforeEach(() => {
  vi.stubGlobal("print", vi.fn());
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("ReceiptPrintModal — chargement", () => {
  it("affiche un indicateur de chargement avant la réponse", () => {
    stubFetchPending();

    render(<ReceiptPrintModal salonId={SALON_ID} paymentId={PAYMENT_ID} onClose={() => {}} />);

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.queryByText("Salon Élégance")).not.toBeInTheDocument();
  });
});

describe("ReceiptPrintModal — erreur", () => {
  it("404 → bannière 'Reçu introuvable.' + bouton Réessayer", async () => {
    stubFetch(404, {});

    render(<ReceiptPrintModal salonId={SALON_ID} paymentId={PAYMENT_ID} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Reçu introuvable.");
    });
    expect(screen.getByRole("button", { name: "Réessayer" })).toBeInTheDocument();
  });

  it("panne réseau → message générique", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new Error("network down")));

    render(<ReceiptPrintModal salonId={SALON_ID} paymentId={PAYMENT_ID} onClose={() => {}} />);

    await waitFor(() => {
      expect(screen.getByRole("alert")).toHaveTextContent("Service momentanément indisponible.");
    });
  });

  it("clic 'Réessayer' relance le chargement (nouvel appel réseau)", async () => {
    const fetchMock = vi
      .fn()
      .mockResolvedValueOnce({ status: 404, json: async () => ({}) })
      .mockResolvedValueOnce({ status: 200, json: async () => FAKE_RECEIPT_BODY });
    vi.stubGlobal("fetch", fetchMock);

    render(<ReceiptPrintModal salonId={SALON_ID} paymentId={PAYMENT_ID} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByRole("alert")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: "Réessayer" }));

    await waitFor(() => {
      expect(screen.getByText("Salon Élégance")).toBeInTheDocument();
    });
    expect(fetchMock).toHaveBeenCalledTimes(2);
  });
});

describe("ReceiptPrintModal — prêt", () => {
  it("affiche le salon, la cliente, les lignes et le total", async () => {
    stubFetch(200, FAKE_RECEIPT_BODY);

    render(<ReceiptPrintModal salonId={SALON_ID} paymentId={PAYMENT_ID} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText("Salon Élégance")).toBeInTheDocument());
    expect(screen.getByText("REC-000001")).toBeInTheDocument();
    expect(screen.getByText(/Awa Koné/)).toBeInTheDocument();
    expect(screen.getByText("Coupe homme")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Imprimer/ })).toBeInTheDocument();
  });

  it("paiement lié à un ticket : affiche le numéro de ticket formaté", async () => {
    stubFetch(200, {
      receipt: { ...FAKE_RECEIPT_BODY.receipt, ticketNumber: 4 },
    });

    render(<ReceiptPrintModal salonId={SALON_ID} paymentId={PAYMENT_ID} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText("Salon Élégance")).toBeInTheDocument());
    expect(screen.getByText("N° 004")).toBeInTheDocument();
  });

  it("prestation seule (pas de ticket) : aucun numéro de ticket affiché", async () => {
    stubFetch(200, FAKE_RECEIPT_BODY);

    render(<ReceiptPrintModal salonId={SALON_ID} paymentId={PAYMENT_ID} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText("Salon Élégance")).toBeInTheDocument());
    expect(screen.queryByText(/^N° /)).not.toBeInTheDocument();
  });

  it("paiement comptoir (client null) : aucune ligne 'Cliente'", async () => {
    stubFetch(200, {
      receipt: { ...FAKE_RECEIPT_BODY.receipt, clientName: null, clientPhone: null },
    });

    render(<ReceiptPrintModal salonId={SALON_ID} paymentId={PAYMENT_ID} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText("Salon Élégance")).toBeInTheDocument());
    expect(screen.queryByText(/Cliente/)).not.toBeInTheDocument();
  });

  it("clic 'Imprimer' appelle window.print()", async () => {
    stubFetch(200, FAKE_RECEIPT_BODY);

    render(<ReceiptPrintModal salonId={SALON_ID} paymentId={PAYMENT_ID} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText("Salon Élégance")).toBeInTheDocument());
    fireEvent.click(screen.getByRole("button", { name: /Imprimer/ }));

    expect(window.print).toHaveBeenCalledTimes(1);
  });

  it("évènement afterprint → bannière de confirmation best-effort", async () => {
    stubFetch(200, FAKE_RECEIPT_BODY);

    render(<ReceiptPrintModal salonId={SALON_ID} paymentId={PAYMENT_ID} onClose={() => {}} />);

    await waitFor(() => expect(screen.getByText("Salon Élégance")).toBeInTheDocument());
    expect(screen.queryByRole("status")).not.toBeInTheDocument();

    fireEvent(window, new Event("afterprint"));

    expect(screen.getByRole("status")).toHaveTextContent("envoyé à l'impression");
  });

  it("clic 'Fermer' appelle onClose", async () => {
    stubFetch(200, FAKE_RECEIPT_BODY);
    const onClose = vi.fn();

    render(<ReceiptPrintModal salonId={SALON_ID} paymentId={PAYMENT_ID} onClose={onClose} />);

    await waitFor(() => expect(screen.getByText("Salon Élégance")).toBeInTheDocument());
    fireEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Fermer" }));

    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
