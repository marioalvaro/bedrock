import { describe, expect, it } from "vitest";

import { answerOut, classificationRun, classifierStatus } from "@/test/classification";

import {
  answerActions,
  chosenClassifier,
  confidenceText,
  configuredClassifiers,
  costText,
  estimateText,
  modeLabel,
  proposalText,
  providerName,
  runNotice,
  runProgressText,
  statusText,
  tokensLeft,
  tokensText,
} from "./classify";

const candidates = [
  { code: "sga", label: "SG&A" },
  { code: "rnd", label: "Research and development" },
];

describe("proposalText", () => {
  it("names one row by its label", () => {
    expect(proposalText(["sga"], candidates)).toBe("SG&A");
  });

  it("says Other for no row", () => {
    expect(proposalText([], candidates)).toBe("Other");
  });

  it("says Combined for several rows, in the answer's order", () => {
    expect(proposalText(["rnd", "sga"], candidates)).toBe(
      "Combined: Research and development + SG&A",
    );
  });

  it("falls back to the code for a row that is not a candidate", () => {
    expect(proposalText(["capex"], candidates)).toBe("capex");
  });
});

describe("confidenceText", () => {
  it("reads as a whole percentage", () => {
    expect(confidenceText("0.9500")).toBe("95%");
    expect(confidenceText("1.0000")).toBe("100%");
    expect(confidenceText("0.0040")).toBe("0%");
    expect(confidenceText("0.8750")).toBe("88%");
  });
});

describe("statusText", () => {
  it("names each status", () => {
    expect(statusText("proposed")).toBe("Proposed");
    expect(statusText("accepted")).toBe("Accepted");
    expect(statusText("rejected")).toBe("Rejected");
  });
});

describe("answerActions", () => {
  it("offers Accept and Reject on a proposal", () => {
    expect(answerActions(answerOut({ status: "proposed" }))).toEqual({
      accept: true,
      reject: true,
    });
  });

  it("offers no Accept on an accepted answer and no Reject on a rejected one", () => {
    expect(answerActions(answerOut({ status: "accepted" }))).toEqual({
      accept: false,
      reject: true,
    });
    expect(answerActions(answerOut({ status: "rejected" }))).toEqual({
      accept: true,
      reject: false,
    });
  });
});

describe("modeLabel", () => {
  it("names the three modes, the last with the threshold", () => {
    expect(modeLabel("off", 0.9)).toBe("Off");
    expect(modeLabel("accepted", 0.9)).toBe("Accepted only");
    expect(modeLabel("all", 0.9)).toBe("All above 90%");
    expect(modeLabel("all", 0.75)).toBe("All above 75%");
  });
});

describe("providerName", () => {
  it("names the provider a classifier sends the lines to", () => {
    expect(providerName("claude:claude-haiku-5-5")).toBe("Anthropic");
    expect(providerName("jev:jev-latest")).toBe("Typesafe");
    expect(providerName("openrouter:openai/gpt-6-luna")).toBe("OpenRouter");
    expect(providerName("openrouter:nvidia/nemotron-3.5-super-vl:free")).toBe("OpenRouter");
  });

  it("falls back to the name's prefix", () => {
    expect(providerName("acme:model")).toBe("acme");
  });
});

describe("configuredClassifiers and chosenClassifier", () => {
  it("lists only the classifiers with a key, in the API's order", () => {
    expect(configuredClassifiers(classifierStatus())).toEqual([
      "claude:claude-haiku-5-5",
      "openrouter:openai/gpt-6-luna",
    ]);
  });

  it("takes the user's pick, else the company's source, else the first", () => {
    const names = ["claude:claude-haiku-5-5", "openrouter:openai/gpt-6-luna"];
    expect(chosenClassifier(names, "openrouter:openai/gpt-6-luna", null)).toBe(
      "openrouter:openai/gpt-6-luna",
    );
    expect(chosenClassifier(names, null, "openrouter:openai/gpt-6-luna")).toBe(
      "openrouter:openai/gpt-6-luna",
    );
    expect(chosenClassifier(names, null, "jev:jev-latest")).toBe("claude:claude-haiku-5-5");
    expect(chosenClassifier(names, "jev:jev-latest", null)).toBe("claude:claude-haiku-5-5");
    expect(chosenClassifier([], null, null)).toBeNull();
  });
});

describe("tokensLeft", () => {
  it("is each budget less what was used, never below 0", () => {
    expect(tokensLeft(classifierStatus())).toEqual({ today: 187500, month: 1520000 });
    expect(tokensLeft(classifierStatus({ used_today: 250000 }))).toMatchObject({ today: 0 });
  });
});

describe("runProgressText and runNotice", () => {
  it("counts the answered lines of a running run", () => {
    expect(
      runProgressText(classificationRun({ status: "running", lines_answered: 3, lines_asked: 10 })),
    ).toBe("Classifying… 3 of 10");
  });

  it("gives the reason of a stopped or failed run, and nothing otherwise", () => {
    const reason = "Stopped: 550 tokens are needed and 0 are left of the daily budget";
    expect(runNotice(classificationRun({ status: "stopped", error: reason }))).toBe(
      `The last run stopped. ${reason}`,
    );
    expect(runNotice(classificationRun({ status: "failed", error: "timed out" }))).toBe(
      "The last run failed. timed out",
    );
    expect(runNotice(classificationRun({ status: "failed", error: null }))).toBe(
      "The last run failed.",
    );
    expect(runNotice(classificationRun({ status: "done" }))).toBeNull();
    const partial = "9 of 12 lines got a usable answer. The others can be asked again.";
    expect(runNotice(classificationRun({ status: "done", error: partial }))).toBe(
      `The last run finished. ${partial}`,
    );
    expect(runNotice(classificationRun({ status: "running" }))).toBeNull();
    expect(runNotice(null)).toBeNull();
  });
});

describe("costText, tokensText and estimateText", () => {
  it("shows a cent or more to the cent, and less to four places", () => {
    expect(costText("0.412300")).toBe("$0.41");
    expect(costText("12.000000")).toBe("$12.00");
    expect(costText("0.002700")).toBe("$0.0027");
    expect(costText("0.000000")).toBe("$0.00");
  });

  it("groups token counts", () => {
    expect(tokensText(1520000)).toBe("1,520,000");
    expect(tokensText(0)).toBe("0");
  });

  it("reads an estimate as input plus output tokens", () => {
    expect(estimateText({ input_tokens: 1200, output_tokens: 300, cost_usd: "0.0027" })).toBe(
      "1,200 in + 300 out",
    );
  });
});
