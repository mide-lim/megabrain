export const GOOGLE_LOGIN_TARGET = "/auth/login?return_to=/inbox";

function GoogleMark() {
  return (
    <svg aria-hidden="true" className="h-5 w-5 shrink-0" viewBox="0 0 24 24">
      <path d="M21.8 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.5a4.7 4.7 0 0 1-2 3.1v2.5h3.2c1.9-1.8 3.1-4.3 3.1-7.4Z" fill="#4285F4" />
      <path d="M12 22c2.7 0 5-.9 6.7-2.4l-3.2-2.5c-.9.6-2 .9-3.5.9-2.7 0-5-1.8-5.8-4.3H2.9v2.6A10 10 0 0 0 12 22Z" fill="#34A853" />
      <path d="M6.2 13.7A6 6 0 0 1 5.9 12c0-.6.1-1.2.3-1.7V7.7H2.9A10 10 0 0 0 2 12c0 1.6.4 3.1.9 4.3l3.3-2.6Z" fill="#FBBC05" />
      <path d="M12 5.9c1.5 0 2.9.5 3.9 1.5l2.9-2.9C17 2.9 14.7 2 12 2a10 10 0 0 0-9.1 5.7l3.3 2.6C7 7.7 9.3 5.9 12 5.9Z" fill="#EA4335" />
    </svg>
  );
}

export default function LoginSession() {
  return (
    <div className="flex min-h-[19rem] flex-col justify-center">
      <p className="text-sm font-semibold text-primary">Acesso do proprietário</p>
      <h2 className="mt-4 text-3xl font-semibold tracking-tight text-foreground">Entre no seu espaço.</h2>
      <p className="mt-4 max-w-md text-base leading-7 text-muted">
        Use a conta Google autorizada para acessar o seu ambiente pessoal de conhecimento e IA.
      </p>
      <div className="mt-8">
        <a
          className="inline-flex min-h-11 w-full items-center justify-center gap-3 rounded-xl bg-primary px-5 py-3 text-sm font-semibold text-white shadow-sm transition-colors hover:bg-[#1f452f] focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-4 focus-visible:outline-primary"
          href={GOOGLE_LOGIN_TARGET}
        >
          <GoogleMark />
          Entrar com Google
        </a>
      </div>
    </div>
  );
}
