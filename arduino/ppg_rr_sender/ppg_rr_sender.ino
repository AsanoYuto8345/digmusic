/*
  Analog PPG (finger clip) -> Beat detection -> Output RR interval (IBI) over Serial

  Output format (per beat):
    RR,<ms>\n
  Example:
    RR,812

  Notes:
  - Uses dynamic threshold based on slow-tracking min/max envelope
  - Simple EMA smoothing
  - Refractory period to prevent double-detection
  - Rejects outlier IBI values
*/

const int PIN_PPG = A0;

// Sampling
const unsigned long SAMPLE_PERIOD_MS = 10;  // 100 Hz
unsigned long lastSampleMs = 0;

// Smoothing (EMA)
float ema = 0.0f;
const float EMA_ALPHA = 0.2f;  // 0.1〜0.3くらいで調整

// Dynamic envelope tracking (slow min/max)
float envMin = 1023.0f;
float envMax = 0.0f;
const float ENV_DECAY = 0.995f;  // 0.99〜0.999で調整（大きいほどゆっくり追従）

// Beat detection
bool above = false;
unsigned long lastBeatMs = 0;

// Guard rails
const unsigned long REFRACTORY_MS = 280;   // 不応期（250〜350で調整）
const unsigned long IBI_MIN_MS = 300;      // 200 bpm 相当
const unsigned long IBI_MAX_MS = 2000;     // 30 bpm 相当

// Threshold ratio between min/max (dynamic)
const float THRESH_RATIO = 0.65f; // 0.55〜0.75で調整（上げると厳しめ）

void setup() {
  Serial.begin(115200);
  delay(300);

  // 初期値の安定化用に数回読んでEMA初期化
  int v = analogRead(PIN_PPG);
  ema = (float)v;
  envMin = ema;
  envMax = ema;

  Serial.println("READY");
}

void loop() {
  unsigned long now = millis();
  if (now - lastSampleMs < SAMPLE_PERIOD_MS) return;
  lastSampleMs = now;

  int raw = analogRead(PIN_PPG);

  // EMA smoothing
  ema = EMA_ALPHA * raw + (1.0f - EMA_ALPHA) * ema;

  // Update envelope with slow decay
  // envMin drifts up slowly, envMax drifts down slowly
  envMin = min(envMin, ema);
  envMax = max(envMax, ema);

  // Apply decay so min/max can follow changes over time
  envMin = envMin * (1.0f - (1.0f - ENV_DECAY)) + ema * (1.0f - ENV_DECAY); // drift toward ema slowly
  envMax = envMax * (1.0f - (1.0f - ENV_DECAY)) + ema * (1.0f - ENV_DECAY);

  // Ensure envelope has some width
  float range = envMax - envMin;
  if (range < 10.0f) {
    // まだ信号が弱い/初期でレンジが狭い → 検出しない
    above = false;
    return;
  }

  float threshold = envMin + THRESH_RATIO * range;

  // Beat detection using rising threshold crossing
  // Detect transition: below->above as a beat candidate
  bool isAbove = (ema > threshold);

  if (!above && isAbove) {
    // rising edge
    unsigned long dt = now - lastBeatMs;

    // Refractory + outlier reject
    if (dt >= REFRACTORY_MS && dt >= IBI_MIN_MS && dt <= IBI_MAX_MS) {
      lastBeatMs = now;
      Serial.print("RR,");
      Serial.println(dt);
    }
  }

  above = isAbove;

  // （任意）デバッグ：波形/しきい値を見たいなら下を有効化
  // Serial.print(raw); Serial.print(",");
  // Serial.print((int)ema); Serial.print(",");
  // Serial.println((int)threshold);
}
