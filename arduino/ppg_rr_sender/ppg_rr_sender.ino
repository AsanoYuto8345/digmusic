/*
  Ultra simple fixed-threshold PPG beat detector
  (tuned for your waveform: small amplitude, clean AC)

  raw -> baseline remove -> ac
  if ac > THRESH_AC and rising edge -> beat

  Output:
    RR,<ms>
*/

const int PIN_PPG = A0;

// Sampling
const unsigned long SAMPLE_PERIOD_MS = 10;  // 100Hz
unsigned long lastSampleMs = 0;

// Guard
const unsigned long REFRACTORY_MS = 280;
const unsigned long IBI_MIN_MS = 500;
const unsigned long IBI_MAX_MS = 2000;

// ===== Signal processing =====
const float BASE_ALPHA = 0.005f;   // baseline追従（遅めでOK）
const float AC_ALPHA   = 0.30f;    // AC平滑

// ===== Fixed threshold (FOR YOU) =====
const float THRESH_AC = 1.6f;      // ★ここが心臓（1.0〜1.6で微調整）

// ===== State =====
float baseline = 0.0f;
float ac = 0.0f;

bool above = false;
unsigned long lastBeatMs = 0;

void setup() {
  Serial.begin(115200);
  delay(300);

  int v = analogRead(PIN_PPG);
  baseline = (float)v;
  ac = 0.0f;
  lastBeatMs = millis();

  Serial.println("READY");
}

void loop() {
  unsigned long now = millis();
  if (now - lastSampleMs < SAMPLE_PERIOD_MS) return;
  lastSampleMs = now;

  int raw = analogRead(PIN_PPG);

  // ---- baseline remove ----
  baseline = baseline + BASE_ALPHA * ((float)raw - baseline);
  float x = (float)raw - baseline;

  // ---- AC smooth ----
  ac = ac + AC_ALPHA * (x - ac);

  // ---- fixed threshold crossing ----
  bool isAbove = (ac > THRESH_AC);

  if (!above && isAbove) {
    unsigned long dt = now - lastBeatMs;

    if (dt >= REFRACTORY_MS && dt >= IBI_MIN_MS && dt <= IBI_MAX_MS) {
      lastBeatMs = now;
      Serial.print("RR,");
      Serial.println(dt);
    }
  }

  above = isAbove;

  // ===== debug (optional) =====
  // ac を見たいとき（プロッタ用）
  // int acScaled = (int)(ac * 20.0f + 512.0f);
  // Serial.println(acScaled);
}
