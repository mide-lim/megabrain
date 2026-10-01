import { OpenPaperclipButton } from "../../components/open-paperclip-button";

type DevelopmentPageContentProps = {
  paperclipAvailable: boolean;
};

export function DevelopmentPageContent({ paperclipAvailable }: DevelopmentPageContentProps) {
  return (
    <section
      aria-labelledby="development-title"
      className="max-w-2xl rounded-2xl border border-border bg-surface px-6 py-10 shadow-[0_12px_30px_rgba(32,37,34,0.06)] sm:px-8 sm:py-12"
    >
      <p className="inline-flex items-center gap-2 rounded-full bg-accent px-3 py-1.5 text-sm font-semibold text-primary">
        <span aria-hidden="true" className="h-2 w-2 rounded-full bg-success" />
        Entrega controlada
      </p>
      <h1
        className="mt-6 text-4xl font-semibold tracking-tight text-foreground text-balance"
        id="development-title"
      >
        Desenvolvimento
      </h1>
      <p className="mt-5 max-w-xl text-base leading-7 text-muted sm:text-lg">
        Abra o Paperclip para acompanhar o desenvolvimento do MegaBrain. Mudanças nesta área passam
        por revisão e aprovação antes de qualquer promoção.
      </p>
      <section
        aria-label="Status do Paperclip"
        className="mt-8 rounded-xl border border-border bg-background p-5"
      >
        <p className="text-sm font-semibold text-foreground">Cockpit Paperclip</p>
        <p
          className={`mt-2 text-sm font-medium ${
            paperclipAvailable ? "text-success" : "text-danger"
          }`}
          role="status"
        >
          {paperclipAvailable ? "Paperclip online" : "Indisponível"}
        </p>
        <div className="mt-5 border-t border-border pt-5">
          <OpenPaperclipButton />
        </div>
      </section>
    </section>
  );
}
