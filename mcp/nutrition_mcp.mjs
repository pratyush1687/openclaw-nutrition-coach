#!/usr/bin/env node
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

const base = process.env.NUTRITION_API_BASE || "http://nutrition-jobs:8080";
const token = process.env.NUTRITION_JOB_TOKEN || "";

function withToken(path) {
  if (!token) return `${base}${path}`;
  return `${base}${path}${path.includes("?") ? "&" : "?"}token=${encodeURIComponent(token)}`;
}

async function get(path) {
  const res = await fetch(withToken(path));
  const text = await res.text();
  if (!res.ok) throw new Error(text || `HTTP ${res.status}`);
  const ctype = res.headers.get("content-type") || "";
  return ctype.includes("json") ? JSON.parse(text) : text;
}

async function post(path, payload) {
  const res = await fetch(withToken(path), {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  const text = await res.text();
  if (!res.ok) throw new Error(text || `HTTP ${res.status}`);
  return JSON.parse(text);
}

function asText(value) {
  return {
    content: [
      {
        type: "text",
        text: typeof value === "string" ? value : JSON.stringify(value, null, 2),
      },
    ],
  };
}

const server = new McpServer({
  name: "nutrition-coach",
  version: "1.0.0",
});

const userFields = {
  user_id: z.number().int().optional(),
  user_name: z.string().optional(),
  telegram_user_id: z.string().optional(),
};

function userQuery(args) {
  const params = new URLSearchParams();
  for (const key of ["user_id", "user_name", "telegram_user_id"]) {
    if (args?.[key] !== undefined) params.set(key, String(args[key]));
  }
  const text = params.toString();
  return text ? `?${text}` : "";
}

server.tool("get_today", "Read today's nutrition totals and targets for one user.", userFields, async (args) => asText(await get(`/today${userQuery(args)}`)));
server.tool(
  "get_logs",
  "Read recent meal, weight, water, steps, or workout logs with ids so a previous entry can be corrected.",
  {
    ...userFields,
    kind: z.enum(["all", "meals", "meal", "weights", "weight", "water", "steps", "workouts", "workout"]).optional().default("all"),
    limit: z.number().int().min(1).max(50).optional().default(10),
  },
  async (args) => {
    const params = new URLSearchParams();
    for (const key of ["user_id", "user_name", "telegram_user_id", "kind", "limit"]) {
      if (args?.[key] !== undefined) params.set(key, String(args[key]));
    }
    return asText(await get(`/logs?${params.toString()}`));
  },
);

server.tool(
  "upsert_user",
  "Create or update a household member profile and targets.",
  {
    user_id: z.number().int().optional(),
    name: z.string(),
    telegram_user_id: z.string().optional(),
    age: z.number().int().optional(),
    sex: z.string().optional(),
    height_cm: z.number().optional(),
    starting_weight_kg: z.number().optional(),
    goal_weight_kg: z.number().optional(),
    role: z.string().optional().default("member"),
    timezone: z.string().optional().default("Asia/Kolkata"),
    targets: z.object({
      calories_kcal: z.number().int().optional(),
      protein_g: z.number().int().optional(),
      fibre_g: z.number().int().optional(),
      water_l: z.number().optional(),
      steps: z.number().int().optional(),
    }).optional().default({}),
  },
  async (args) => asText(await post("/users", args)),
);

server.tool(
  "log_meal",
  "Persist an estimated or confirmed meal with calories, protein, carbs, fat, and fibre.",
  {
    ...userFields,
    meal_type: z.string(),
    calories: z.number(),
    protein: z.number(),
    carbs: z.number().optional().default(0),
    fat: z.number().optional().default(0),
    fibre: z.number().optional().default(0),
    confidence: z.string().optional().default("ai-estimated"),
    notes: z.string().optional().default(""),
    confirmed_by_user: z.boolean().optional().default(false),
    skipped: z.boolean().optional().default(false),
  },
  async (args) => asText(await post("/log-meal", args)),
);
server.tool(
  "update_meal",
  "Correct a previously logged meal by id. Use get_logs first unless the id is already known.",
  {
    ...userFields,
    id: z.number().int(),
    timestamp: z.string().optional(),
    meal_type: z.string().optional(),
    calories: z.number().optional(),
    protein: z.number().optional(),
    carbs: z.number().optional(),
    fat: z.number().optional(),
    fibre: z.number().optional(),
    confidence: z.string().optional(),
    notes: z.string().optional(),
    confirmed_by_user: z.boolean().optional(),
    skipped: z.boolean().optional(),
  },
  async (args) => asText(await post("/update-meal", args)),
);

server.tool("log_weight", "Persist a body-weight log in kilograms.", { ...userFields, weight_kg: z.number() }, async (args) => asText(await post("/log-weight", args)));
server.tool("log_water", "Persist a water log in litres.", { ...userFields, litres: z.number() }, async (args) => asText(await post("/log-water", args)));
server.tool("log_steps", "Persist the latest step count.", { ...userFields, steps: z.number().int() }, async (args) => asText(await post("/log-steps", args)));
server.tool(
  "update_weight",
  "Correct a previously logged body-weight entry by id. Use get_logs first unless the id is already known.",
  { ...userFields, id: z.number().int(), timestamp: z.string().optional(), weight_kg: z.number().optional() },
  async (args) => asText(await post("/update-weight", args)),
);
server.tool(
  "update_water",
  "Correct a previously logged water entry by id. Use get_logs first unless the id is already known.",
  { ...userFields, id: z.number().int(), timestamp: z.string().optional(), litres: z.number().optional() },
  async (args) => asText(await post("/update-water", args)),
);
server.tool(
  "update_steps",
  "Correct a previously logged step entry by id. Use get_logs first unless the id is already known.",
  { ...userFields, id: z.number().int(), timestamp: z.string().optional(), steps: z.number().int().optional() },
  async (args) => asText(await post("/update-steps", args)),
);
server.tool(
  "log_workout",
  "Persist a workout completion log.",
  { ...userFields, workout_type: z.string().optional().default("strength training"), completed: z.boolean().optional().default(true), notes: z.string().optional().default("") },
  async (args) => asText(await post("/log-workout", args)),
);
server.tool(
  "update_workout",
  "Correct a previously logged workout entry by id. Use get_logs first unless the id is already known.",
  {
    ...userFields,
    id: z.number().int(),
    timestamp: z.string().optional(),
    workout_type: z.string().optional(),
    completed: z.boolean().optional(),
    notes: z.string().optional(),
  },
  async (args) => asText(await post("/update-workout", args)),
);
server.tool(
  "update_targets",
  "Update daily nutrition and activity targets.",
  {
    ...userFields,
    calories_kcal: z.number().int().optional(),
    protein_g: z.number().int().optional(),
    fibre_g: z.number().int().optional(),
    water_l: z.number().optional(),
    steps: z.number().int().optional(),
  },
  async (args) => asText(await post("/targets", args)),
);
server.tool(
  "upsert_known_food",
  "Create or update a user-confirmed known food or common meal.",
  {
    ...userFields,
    name: z.string(),
    serving_description: z.string().optional().default(""),
    calories: z.number(),
    protein: z.number(),
    carbs: z.number().optional().default(0),
    fat: z.number().optional().default(0),
    fibre: z.number().optional().default(0),
    source: z.enum(["user-confirmed", "ai-estimated"]).optional().default("user-confirmed"),
    household: z.boolean().optional().default(true),
  },
  async (args) => asText(await post("/known-food", args)),
);
server.tool(
  "set_preference",
  "Persist a food preference, menu note, disliked food, preferred ingredient, or coaching preference.",
  { ...userFields, key: z.string(), value: z.string(), household: z.boolean().optional().default(false) },
  async (args) => asText(await post("/preference", args)),
);
server.tool("morning_plan", "Generate today's concise morning meal plan for one user.", { ...userFields, send: z.boolean().optional().default(false) }, async (args) => asText(await get(`/morning-plan${userQuery(args)}${userQuery(args) ? "&" : "?"}send=${args.send ? "1" : "0"}`)));
server.tool("scorecard", "Generate today's evening scorecard for one user.", { ...userFields, send: z.boolean().optional().default(false) }, async (args) => asText(await get(`/scorecard${userQuery(args)}${userQuery(args) ? "&" : "?"}send=${args.send ? "1" : "0"}`)));
server.tool("weekly_summary", "Generate the 7-day weight and adherence summary for one user.", { ...userFields, send: z.boolean().optional().default(false) }, async (args) => asText(await get(`/weekly${userQuery(args)}${userQuery(args) ? "&" : "?"}send=${args.send ? "1" : "0"}`)));

await server.connect(new StdioServerTransport());
