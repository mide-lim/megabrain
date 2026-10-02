// Synthetic data only. This module never imports application secrets or database clients.
export const COOKIE = "mb_visual_preview";
export const CSRF = "visual-preview-csrf";
export function initialState() {
  return { unavailable: false, paperclip: true, reels: [
    { id: 42, title: "Prévia — RFID na prática", creator: "@preview_maker",
      shortcode: "preview-rfid", caption: "Material fictício para revisar a interface.",
      categories: ["Tecnologia"], duration_seconds: 35, received_at: "2026-10-01T12:00:00Z",
      has_transcript: true, download_status: "downloaded", curation_status: "organized",
      transcription_status: "completed" },
    { id: 43, title: "Prévia — Learning with projects", creator: "@preview_learning",
      shortcode: "preview-learning", caption: "Synthetic English-language example.",
      categories: [], duration_seconds: 90, received_at: "2026-10-01T12:00:00Z",
      has_transcript: false, download_status: "downloaded", curation_status: "inbox",
      transcription_status: "not_requested" }
  ] };
}
export function detail(item) {
  return { ...item, original_url: null, downloaded_at: item.received_at,
    filename: null, mime_type: null, file_size_bytes: null,
    transcript: { available: item.has_transcript,
      text: item.has_transcript ? "Exemplo fictício: conectar um leitor RFID ao projeto." : null,
      language: item.has_transcript ? "pt-BR" : null,
      completed_at: item.has_transcript ? item.received_at : null },
    categories: { assigned: item.categories.map(() => ({ id: 1, name: "Tecnologia" })),
      available: [{ id: 1, name: "Tecnologia" }, { id: 2, name: "Aprendizado" }] },
    video: { available: false, src: null } };
}
export function projection(item) {
  return { id: item.id, download_status: item.download_status,
    curation_status: item.curation_status, transcription_status: item.transcription_status };
}
