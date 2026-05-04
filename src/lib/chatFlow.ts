import { providerChat } from "./ipc";
import type { ChatMessage, ProviderId } from "./types";
import { PROVIDERS } from "./types";

export type ChatFlowPhase = "responding" | "drafting" | "reviewing" | "synthesizing";

type PhaseHandler = (phase: ChatFlowPhase) => void;

export async function runSingleProviderChat(
  provider: ProviderId,
  messages: ChatMessage[],
  project: string | null,
  onPhase: PhaseHandler,
): Promise<string> {
  onPhase("responding");
  return providerChat(provider, buildChatPrompt(messages), project);
}

export async function runAdvisedChat(
  provider: ProviderId,
  advisor: ProviderId,
  messages: ChatMessage[],
  project: string | null,
  onPhase: PhaseHandler,
): Promise<string> {
  const userMessage = messages[messages.length - 1]?.content ?? "";
  const primaryName = PROVIDERS[provider].label;
  const advisorName = PROVIDERS[advisor].label;

  onPhase("drafting");
  const draft = await providerChat(provider, buildDraftPrompt(messages), project);

  onPhase("reviewing");
  const review = await providerChat(
    advisor,
    buildAdvisorPrompt(userMessage, draft, primaryName),
    project,
  );

  onPhase("synthesizing");
  return providerChat(
    provider,
    buildFinalPrompt(messages, draft, review, advisorName),
    project,
  );
}

function buildChatPrompt(messages: ChatMessage[]): string {
  const transcript = messages
    .map((message) => {
      const speaker = message.role === "user" ? "User" : "Assistant";
      return `${speaker}: ${message.content}`;
    })
    .join("\n\n");

  return [
    "You are a chat assistant in a multi-provider desktop app.",
    "Reply only to the latest user message.",
    "Do not repeat this transcript unless the user asks for it.",
    "",
    transcript,
  ].join("\n");
}

function buildDraftPrompt(messages: ChatMessage[]): string {
  return [
    "You are the primary provider in a multi-provider chat orchestration.",
    "Write a clear draft answer to the latest user message.",
    "Do not mention that this is a draft.",
    "",
    buildChatPrompt(messages),
  ].join("\n");
}

function buildAdvisorPrompt(
  userMessage: string,
  draft: string,
  primaryName: string,
): string {
  return [
    "You are the advisor provider in a multi-provider chat orchestration.",
    `The primary provider (${primaryName}) wrote this draft answer:`,
    "",
    draft,
    "",
    "User's latest message:",
    userMessage,
    "",
    "Review the draft. Point out what should be corrected, strengthened, removed, or kept.",
    "Return concise, actionable feedback for the primary provider. Do not answer the user directly.",
  ].join("\n");
}

function buildFinalPrompt(
  messages: ChatMessage[],
  draft: string,
  review: string,
  advisorName: string,
): string {
  return [
    "You are the primary provider in a multi-provider chat orchestration.",
    "Use your draft and the advisor feedback to produce the final answer for the user.",
    "Do not expose the orchestration steps unless the user asks.",
    "Reply only with the final answer.",
    "",
    "Conversation:",
    buildChatPrompt(messages),
    "",
    "Your draft:",
    draft,
    "",
    `${advisorName}'s feedback:`,
    review,
  ].join("\n");
}
