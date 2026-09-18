import { experimental_evaluate as evaluate } from "ai";

let raw = "";
for await (const chunk of process.stdin) raw += chunk;

const payload = JSON.parse(raw || "{}");
if (!payload.state || !payload.questions) {
  throw new Error("state and questions are required");
}

const result = await evaluate({
  model: "typesafe-ai/jev",
  state: payload.state,
  questions: payload.questions,
  providerOptions: {
    gateway: {
      zeroDataRetention: true,
    },
  },
});

process.stdout.write(JSON.stringify({
  answers: result.answers,
  metadata: {
    providerMetadata: result.providerMetadata ?? null,
    usage: result.usage ?? null,
  },
}));
