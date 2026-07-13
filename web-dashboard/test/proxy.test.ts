// Tests unitaires — garde `proxy` (deny-by-default, présence du cookie de
// session). `next/server` est mocké : aucun runtime Next n'est requis.
// La validité réelle du jeton est vérifiée dans le layout serveur (#14) ;
// ici on teste uniquement la décision « cookie présent / absent ».

import { beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("next/server", () => ({
  NextResponse: {
    redirect: vi.fn((url: URL) => ({ _mocked: "redirect", destination: url.toString() })),
    next: vi.fn(() => ({ _mocked: "next" })),
  },
}));

import { NextResponse } from "next/server";
import type { NextRequest } from "next/server";

import { proxy } from "../proxy";
import { SESSION_COOKIE } from "../src/adapters/api/session-cookie-names";

type MockResponse = { _mocked: "redirect"; destination: string } | { _mocked: "next" };

function makeRequest(cookies: Record<string, string>, url = "http://localhost/gerant"): NextRequest {
  return {
    cookies: {
      has: (name: string) => Object.prototype.hasOwnProperty.call(cookies, name),
      get: (name: string) =>
        Object.prototype.hasOwnProperty.call(cookies, name)
          ? { value: cookies[name] }
          : undefined,
    },
    url,
  } as unknown as NextRequest;
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("proxy — garde de présence de cookie", () => {
  it("redirige vers /login quand le cookie de session est absent", () => {
    const req = makeRequest({});
    const res = proxy(req) as MockResponse;
    expect(NextResponse.redirect).toHaveBeenCalledOnce();
    expect(NextResponse.next).not.toHaveBeenCalled();
    expect(res._mocked).toBe("redirect");
  });

  it("appelle NextResponse.next() quand le cookie de session est présent", () => {
    const req = makeRequest({ [SESSION_COOKIE]: "tok" });
    const res = proxy(req) as MockResponse;
    expect(NextResponse.next).toHaveBeenCalledOnce();
    expect(NextResponse.redirect).not.toHaveBeenCalled();
    expect(res._mocked).toBe("next");
  });

  it("l'URL de redirection pointe vers /login", () => {
    proxy(makeRequest({}));
    const callArg = (NextResponse.redirect as ReturnType<typeof vi.fn>).mock.calls[0][0] as URL;
    expect(callArg.pathname).toBe("/login");
  });

  it("conserve l'origine de la requête dans la redirection", () => {
    proxy(makeRequest({}, "http://app.example.com/gerant"));
    const callArg = (NextResponse.redirect as ReturnType<typeof vi.fn>).mock.calls[0][0] as URL;
    expect(callArg.origin).toBe("http://app.example.com");
    expect(callArg.pathname).toBe("/login");
  });

  it("redirige sur une sous-route /gerant/planning sans cookie", () => {
    proxy(makeRequest({}, "http://localhost/gerant/planning"));
    expect(NextResponse.redirect).toHaveBeenCalledOnce();
    const callArg = (NextResponse.redirect as ReturnType<typeof vi.fn>).mock.calls[0][0] as URL;
    expect(callArg.pathname).toBe("/login");
  });

  it("laisse passer une sous-route /gerant/employes avec cookie", () => {
    proxy(makeRequest({ [SESSION_COOKIE]: "tok" }, "http://localhost/gerant/employes"));
    expect(NextResponse.next).toHaveBeenCalledOnce();
    expect(NextResponse.redirect).not.toHaveBeenCalled();
  });

  it("n'est pas trompé par un cookie au nom différent", () => {
    // Un cookie 'autre_cookie' ne doit pas satisfaire la garde
    proxy(makeRequest({ autre_cookie: "tok" }));
    expect(NextResponse.redirect).toHaveBeenCalledOnce();
  });
});

describe("SESSION_COOKIE — constante publique", () => {
  it("expose le nom du cookie de session (cl_session)", () => {
    expect(SESSION_COOKIE).toBe("cl_session");
  });
});
