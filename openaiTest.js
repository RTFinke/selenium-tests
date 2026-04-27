import 'dotenv/config';
import OpenAI from "openai";

const client = new OpenAI({
  apiKey: process.env.OPENAI_API_KEY,
});

async function test() {
  try {
    const response = await client.responses.create({
      model: "gpt-4.1-mini",
      input: "Say hello and confirm the API key works.",
    });

    console.log("✅ API key works!");
    console.log(response.output[0].content[0].text);
  } catch (err) {
    console.error("❌ Error:", err.message);
  }
}

test();