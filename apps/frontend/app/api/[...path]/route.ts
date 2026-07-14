import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";
export const runtime = "nodejs";

const HOP_BY_HOP_REQUEST_HEADERS = new Set([
  "connection",
  "content-length",
  "host",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

const HOP_BY_HOP_RESPONSE_HEADERS = new Set([
  "connection",
  "content-encoding",
  "content-length",
  "keep-alive",
  "proxy-authenticate",
  "proxy-authorization",
  "te",
  "trailer",
  "transfer-encoding",
  "upgrade",
]);

type RouteContext = {
  params: Promise<{
    path: string[];
  }>;
};

function backendBaseUrl(): string {
  const baseUrl = process.env.BACKEND_INTERNAL_URL?.trim().replace(/\/$/, "");
  if (!baseUrl) {
    throw new Error("BACKEND_INTERNAL_URL is required for /api proxying.");
  }
  return baseUrl;
}

function targetUrl(request: NextRequest, path: string[]): string {
  const encodedPath = path.map((part) => encodeURIComponent(part)).join("/");
  const url = new URL(`${backendBaseUrl()}/api/${encodedPath}`);
  url.search = request.nextUrl.search;
  return url.toString();
}

function requestHeaders(request: NextRequest): Headers {
  const headers = new Headers();
  request.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_REQUEST_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });
  return headers;
}

function responseHeaders(upstream: Response): Headers {
  const headers = new Headers();
  upstream.headers.forEach((value, key) => {
    if (!HOP_BY_HOP_RESPONSE_HEADERS.has(key.toLowerCase())) {
      headers.set(key, value);
    }
  });
  return headers;
}

async function proxy(request: NextRequest, context: RouteContext): Promise<Response> {
  const { path } = await context.params;

  let url: string;
  try {
    url = targetUrl(request, path);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Invalid backend proxy configuration." },
      { status: 500 },
    );
  }

  const hasBody = request.method !== "GET" && request.method !== "HEAD";
  const init: RequestInit & { duplex?: "half" } = {
    method: request.method,
    headers: requestHeaders(request),
    body: hasBody ? request.body : undefined,
    redirect: "manual",
  };
  if (hasBody) {
    init.duplex = "half";
  }

  let upstream: Response;
  try {
    upstream = await fetch(url, init);
  } catch (error) {
    return NextResponse.json(
      { error: error instanceof Error ? error.message : "Backend API request failed." },
      { status: 502 },
    );
  }

  return new Response(request.method === "HEAD" ? null : upstream.body, {
    status: upstream.status,
    statusText: upstream.statusText,
    headers: responseHeaders(upstream),
  });
}

export {
  proxy as DELETE,
  proxy as GET,
  proxy as HEAD,
  proxy as OPTIONS,
  proxy as PATCH,
  proxy as POST,
  proxy as PUT,
};
