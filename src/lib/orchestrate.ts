import { onPtyOutput, ptyWrite } from "./ipc";

export type OrchPhase = "drafting" | "reviewing" | "synthesizing" | "done";

function stripAnsi(raw: string): string {
  return raw
    .replace(/\x1b\[[0-9;]*[A-Za-z]/g, "")
    .replace(/\x1b\][^\x07]*\x07/g, "")
    .replace(/\r\n/g, "\n")
    .replace(/\r/g, "\n")
    .trim();
}

/**
 * 특정 tabId에서 silenceMs 동안 출력이 없으면 resolve.
 * maxWaitMs를 초과하면 강제 resolve.
 */
function captureUntilSilent(
  tabId: string,
  silenceMs = 3000,
  maxWaitMs = 60_000,
): Promise<string> {
  return new Promise((resolve) => {
    let buffer = "";
    let silenceTimer: ReturnType<typeof setTimeout> | null = null;

    const finish = (unlisten: Promise<() => void>) => {
      unlisten.then((fn) => fn());
      resolve(buffer);
    };

    const unlisten = onPtyOutput(({ tab_id, data }) => {
      if (tab_id !== tabId) return;
      buffer += data;
      if (silenceTimer) clearTimeout(silenceTimer);
      silenceTimer = setTimeout(() => finish(unlisten), silenceMs);
    });

    // 최대 대기 타이머
    const maxTimer = setTimeout(() => {
      if (silenceTimer) clearTimeout(silenceTimer);
      finish(unlisten);
    }, maxWaitMs);

    // silence 타이머가 먼저 끝나면 maxTimer 정리
    unlisten.then(() => clearTimeout(maxTimer));
  });
}

/**
 * draft → review → synth 3단계 오케스트레이션.
 * onPhase: 각 단계 진입 시 호출.
 */
export async function runOrchestrated(
  primaryTabId: string,
  advisorTabId: string,
  message: string,
  onPhase: (phase: OrchPhase) => void,
): Promise<void> {
  // ── 1. Draft ─────────────────────────────────────────
  onPhase("drafting");
  await ptyWrite(primaryTabId, message + "\r");
  const rawDraft = await captureUntilSilent(primaryTabId, 3000);
  const draft = stripAnsi(rawDraft);

  // ── 2. Review ────────────────────────────────────────
  onPhase("reviewing");
  const reviewPrompt =
    `The user asked: "${message}"\n\n` +
    `The primary agent responded:\n${draft}\n\n` +
    `Please review this response: point out issues, suggest improvements, or confirm correctness.`;
  await ptyWrite(advisorTabId, reviewPrompt + "\r");
  const rawReview = await captureUntilSilent(advisorTabId, 3000);
  const review = stripAnsi(rawReview);

  // ── 3. Synthesize ─────────────────────────────────────
  onPhase("synthesizing");
  const synthPrompt =
    `The advisor reviewed your previous response to: "${message}"\n\n` +
    `Advisor feedback:\n${review}\n\n` +
    `Please provide a final, improved answer that incorporates this feedback.`;
  await ptyWrite(primaryTabId, synthPrompt + "\r");

  await captureUntilSilent(primaryTabId, 3000);
  onPhase("done");
}
