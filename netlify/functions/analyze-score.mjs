const headers = {
  "content-type": "application/json; charset=utf-8",
  "access-control-allow-origin": "*",
  "access-control-allow-headers": "content-type",
  "access-control-allow-methods": "POST, OPTIONS",
};

const reply = (statusCode, body) => ({ statusCode, headers, body: JSON.stringify(body) });

export async function handler(event) {
  if (event.httpMethod === "OPTIONS") return reply(204, {});
  if (event.httpMethod !== "POST") return reply(405, { error: "仅支持 POST 请求" });
  if (!process.env.OPENAI_API_KEY) return reply(503, { error: "服务器尚未配置 AI 密钥" });

  try {
    const { image, filename = "score.jpg" } = JSON.parse(event.body || "{}");
    if (!/^data:image\/(jpeg|jpg|png|webp);base64,/.test(image || "")) {
      return reply(400, { error: "请上传 JPG、PNG 或 WEBP 乐谱图片" });
    }
    if (image.length > 12_000_000) return reply(413, { error: "图片过大，请压缩后重试" });

    const prompt = `你是一名严谨的古典和声分析教师。请把图片中的音符视为实际音高，按从左到右的和声节奏分析，不要凭已有文字标注照抄答案。

识别要求：
1. 先读谱号、调号、临时升降记号、移调与八度位置，再判断主调及局部调性。
2. 每个纵向和声事件列出最多四个代表音，顺序为女高、女低、男高、男低；看不清的音写 ?，不可臆造。
3. 功能只用 T、S、D、X：T 主功能，S 下属功能，D 属功能，X 离调或色彩功能。终止四六写 D，证据中注明 K64。
4. 相同和声的持续音不要重复计数；和声真正改变时才新增事件。
5. 必须说明证据与置信度。若图片不清晰，明确写“需复核”。

只返回 JSON，不要 Markdown。结构：
{"key":"调性","summary":"整体说明","chords":[{"index":1,"key":"局部调性","tones":["E5","C5","G4","C3"],"function":"T","inversion":"原位","role":"结构作用","evidence":"判断依据","confidence":0.9}]}

文件名：${filename}`;

    const api = await fetch("https://api.openai.com/v1/responses", {
      method: "POST",
      headers: {
        authorization: `Bearer ${process.env.OPENAI_API_KEY}`,
        "content-type": "application/json",
      },
      body: JSON.stringify({
        model: "gpt-5",
        input: [{
          role: "user",
          content: [
            { type: "input_text", text: prompt },
            { type: "input_image", image_url: image, detail: "high" },
          ],
        }],
      }),
    });

    const result = await api.json();
    if (!api.ok) {
      const message = result?.error?.message || "AI 识谱请求失败";
      return reply(api.status >= 500 ? 502 : api.status, { error: message });
    }
    const text = result.output_text || result.output?.flatMap(x => x.content || []).find(x => x.type === "output_text")?.text || "";
    const clean = text.trim().replace(/^```(?:json)?\s*/i, "").replace(/\s*```$/, "");
    const data = JSON.parse(clean);
    if (!Array.isArray(data.chords)) throw new Error("AI 返回的和声结果格式不完整");
    data.chords = data.chords.slice(0, 80).map((chord, index) => ({
      index: index + 1,
      key: String(chord.key || data.key || "待确认").slice(0, 30),
      tones: Array.isArray(chord.tones) ? chord.tones.slice(0, 4).map(x => String(x).slice(0, 12)) : ["?", "?", "?", "?"],
      function: ["T", "S", "D", "X"].includes(chord.function) ? chord.function : "X",
      inversion: String(chord.inversion || "原位").slice(0, 20),
      role: String(chord.role || "待解释").slice(0, 80),
      evidence: String(chord.evidence || "需结合原谱复核").slice(0, 240),
      confidence: Number.isFinite(Number(chord.confidence)) ? Number(chord.confidence) : null,
    }));
    return reply(200, data);
  } catch (error) {
    return reply(500, { error: error?.message || "识谱服务处理失败" });
  }
}
