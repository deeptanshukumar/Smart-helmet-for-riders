/*
 * Biker Fall Detection System v2
 * Sensors : MPU-9250 (IMU) + VL53L1X (ToF) + MQ gas sensor
 * Actuator: Buzzer
 *
 * Pin map:
 *   MPU-9250 & VL53L1X  SDA → A4   SCL → A5  (shared I2C)
 *   Gas sensor AO       → A0
 *   Buzzer (+)          → D8
 *
 * Serial out 115200 baud, 20 Hz:
 *   ax,ay,az,gx,gy,gz,pitch,roll,accelMag,gyroMag,fall,tilt,dist,state,gas,helmet
 * Serial in:
 *   'F' = trigger fall manually
 *   'R' = reset
 */

#include <Wire.h>
#include <Adafruit_VL53L1X.h>

// ── Pin assignments ────────────────────────────────────────────────
#define GAS_PIN     A0
#define BUZZER_PIN  8

// ── MPU-9250 registers ────────────────────────────────────────────
#define MPU_ADDR     0x68
#define PWR_MGMT_1   0x6B
#define ACCEL_CONFIG 0x1C
#define GYRO_CONFIG  0x1B
#define ACCEL_XOUT_H 0x3B

// ±8g → 4096 LSB/g   |   ±500 °/s → 65.5 LSB/(°/s)
#define ACCEL_SCALE  4096.0f
#define GYRO_SCALE   65.5f

// ── Fall / tilt thresholds ────────────────────────────────────────
#define FREEFALL_G        0.4f
#define IMPACT_G          2.8f
#define TUMBLE_DPS        200.0f
#define FALLEN_CONFIRM_MS 600
#define TILT_WARN         30.0f
#define TILT_CRIT         55.0f

// ── Gas sensor ────────────────────────────────────────────────────
#define GAS_THRESHOLD     400
#define GAS_WARMUP_MS     90000UL   // ignore gas for first 90 s (MQ warm-up)

// ── Helmet detection (ToF) ────────────────────────────────────────
// Tune HELMET_ON_DIST to the distance your sensor reads when the helmet
// is worn (open Serial Monitor after upload — watch the dist field).
// Hysteresis gap prevents flicker: ON threshold < OFF threshold.
#define HELMET_ON_DIST    35        // mm  — dist below this  = head present
#define HELMET_OFF_DIST   95        // mm  — dist above this  = head absent
#define HELMET_CONFIRM    8         // consecutive stable readings to flip state

// ── State machine ─────────────────────────────────────────────────
enum FallState { NORMAL, FREEFALL, IMPACT, FALLEN };
FallState fallState    = NORMAL;
unsigned long impactMs = 0;
float peakGyro         = 0;
bool  manualFall       = false;

Adafruit_VL53L1X tof = Adafruit_VL53L1X();
bool tofReady = false;

// ── Helmet state (debounced, persistent) ──────────────────────────
uint16_t lastDist   = 0;      // last valid ToF reading — persists across loops
bool     helmetOn   = true;   // start true so no false alarm on boot
uint8_t  onStreak   = 0;      // consecutive "head present" readings
uint8_t  offStreak  = 0;      // consecutive "head absent"  readings

// Call every loop with the latest dist (0 = no new reading → keep state).
void updateHelmet(uint16_t dist) {
  if (!tofReady) { helmetOn = true; return; }   // no sensor → bypass entirely

  if (dist == 0) return;                         // no fresh reading → hold state
  lastDist = dist;

  if (dist < HELMET_ON_DIST) {
    onStreak  = min((int)onStreak  + 1, 20);
    offStreak = 0;
    if (onStreak >= HELMET_CONFIRM) helmetOn = true;

  } else if (dist > HELMET_OFF_DIST) {
    offStreak = min((int)offStreak + 1, 20);
    onStreak  = 0;
    if (offStreak >= HELMET_CONFIRM) helmetOn = false;
  }
  // In the hysteresis zone (70–130 mm): keep current state — no change
}

// ── Non-blocking buzzer ───────────────────────────────────────────
unsigned long lastBuzzToggle = 0;
unsigned long lastHelmetBeep = 0;
bool          buzzState      = false;

void updateBuzzer(bool fallen, bool gasAlert) {
  unsigned long now = millis();

  if (fallen) {
    // Fast double-beep: 200 ms on / 200 ms off
    if (now - lastBuzzToggle >= 200) {
      buzzState = !buzzState;
      digitalWrite(BUZZER_PIN, buzzState ? HIGH : LOW);
      lastBuzzToggle = now;
    }

  } else if (gasAlert) {
    // Urgent triple-pip: 150 ms on / 150 ms off
    if (now - lastBuzzToggle >= 150) {
      buzzState = !buzzState;
      digitalWrite(BUZZER_PIN, buzzState ? HIGH : LOW);
      lastBuzzToggle = now;
    }

  } else if (tofReady && !helmetOn) {
    // Gentle reminder pip: one 100 ms beep every 6 s
    // Guard: only fires when ToF is actually initialised and confirms no helmet.
    if (now - lastHelmetBeep >= 6000) {
      digitalWrite(BUZZER_PIN, HIGH);
      delay(100);
      digitalWrite(BUZZER_PIN, LOW);
      lastHelmetBeep = now;
    }

  } else {
    digitalWrite(BUZZER_PIN, LOW);
    buzzState = false;
  }
}

// ── MPU-9250 helpers ──────────────────────────────────────────────
void mpuWrite(uint8_t reg, uint8_t val) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(reg); Wire.write(val);
  Wire.endTransmission();
}

void mpuReadBytes(uint8_t startReg, uint8_t *buf, uint8_t len) {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(startReg);
  Wire.endTransmission(false);
  Wire.requestFrom((uint8_t)MPU_ADDR, len);
  for (uint8_t i = 0; i < len; i++) buf[i] = Wire.read();
}

inline int16_t toInt16(uint8_t hi, uint8_t lo) {
  return (int16_t)((hi << 8) | lo);
}

void initMPU() {
  mpuWrite(PWR_MGMT_1,   0x01);  // wake, PLL with X gyro
  delay(100);
  mpuWrite(ACCEL_CONFIG, 0x10);  // ±8g
  mpuWrite(GYRO_CONFIG,  0x08);  // ±500 °/s
  delay(10);
}

// ── Setup ─────────────────────────────────────────────────────────
void setup() {
  Serial.begin(115200);
  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  Wire.begin();
  Wire.setClock(400000);

  initMPU();

  if (tof.begin(0x29, &Wire)) {
    tof.setTimingBudget(50);
    tof.startRanging();
    tofReady = true;
  }

  Serial.println("READY");
}

// ── Main loop ─────────────────────────────────────────────────────
void loop() {
  // Serial commands
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == 'F') { manualFall = true; }
    if (c == 'R') { manualFall = false; fallState = NORMAL; peakGyro = 0; }
  }

  // ── IMU read (14 bytes: accel + temp + gyro) ──────────────────
  uint8_t buf[14];
  mpuReadBytes(ACCEL_XOUT_H, buf, 14);

  float ax = toInt16(buf[0],  buf[1])  / ACCEL_SCALE;
  float ay = toInt16(buf[2],  buf[3])  / ACCEL_SCALE;
  float az = toInt16(buf[4],  buf[5])  / ACCEL_SCALE;
  float gx = toInt16(buf[8],  buf[9])  / GYRO_SCALE;
  float gy = toInt16(buf[10], buf[11]) / GYRO_SCALE;
  float gz = toInt16(buf[12], buf[13]) / GYRO_SCALE;

  float accelMag = sqrt(ax*ax + ay*ay + az*az);
  float gyroMag  = sqrt(gx*gx + gy*gy + gz*gz);

  float pitch = atan2(ax, sqrt(ay*ay + az*az)) * (180.0f / PI);
  float roll  = atan2(ay, sqrt(ax*ax + az*az)) * (180.0f / PI);

  // Tilt label
  char tiltDir[12] = "Level";
  float tiltMag = sqrt(pitch*pitch + roll*roll);
  if (tiltMag > TILT_CRIT) {
    if (fabs(pitch) >= fabs(roll)) strcpy(tiltDir, pitch > 0 ? "Forward"  : "Backward");
    else                            strcpy(tiltDir, roll  > 0 ? "Right"    : "Left");
  } else if (tiltMag > TILT_WARN) {
    strcpy(tiltDir, "Tilting");
  }

  // ── ToF distance → debounced helmet detection ────────────────
  // freshDist is 0 when no new measurement is ready this iteration.
  // updateHelmet() ignores 0s and only acts on valid readings.
  uint16_t freshDist = 0;
  if (tofReady && tof.dataReady()) {
    int16_t d = tof.distance();
    if (d > 0) freshDist = (uint16_t)d;
    tof.clearInterrupt();
  }
  updateHelmet(freshDist);
  uint16_t dist = (freshDist > 0) ? freshDist : lastDist;  // report last known

  // ── Gas sensor (ignore readings during MQ warm-up period) ────
  int gasValue  = analogRead(GAS_PIN);
  bool gasAlert = (gasValue > GAS_THRESHOLD) && (millis() > GAS_WARMUP_MS);

  // ── Fall detection (only active when helmet worn) ──────────────
  bool fallen = manualFall;

  if (!manualFall) {
    if (helmetOn) {
      switch (fallState) {
        case NORMAL:
          if      (accelMag < FREEFALL_G) { fallState = FREEFALL; }
          else if (accelMag > IMPACT_G)   { fallState = IMPACT; impactMs = millis(); peakGyro = gyroMag; }
          break;

        case FREEFALL:
          if      (accelMag > IMPACT_G)           { fallState = IMPACT; impactMs = millis(); peakGyro = gyroMag; }
          else if (accelMag > FREEFALL_G + 0.3f)  { fallState = NORMAL; }
          break;

        case IMPACT:
          if (gyroMag > peakGyro) peakGyro = gyroMag;
          if (millis() - impactMs > FALLEN_CONFIRM_MS) {
            bool spin    = (peakGyro > TUMBLE_DPS);
            bool posture = (fabs(pitch) > TILT_CRIT || fabs(roll) > TILT_CRIT);
            fallState = (spin || posture) ? FALLEN : NORMAL;
            peakGyro  = 0;
          }
          break;

        case FALLEN:
          break;  // handled below
      }
    } else {
      // Helmet removed mid-ride — only reset if NOT already confirmed fallen.
      // If the rider has fallen, keep the FALLEN state so the buzzer and GUI
      // continue alerting even if the helmet has shifted off the head.
      if (fallState != FALLEN) {
        fallState = NORMAL;
        peakGyro  = 0;
      }
    }

    // ── Regardless of helmet state, if FALLEN → keep fallen = true ──
    if (fallState == FALLEN) fallen = true;
  }

  // State string
  const char *stateStr;
  switch (fallState) {
    case FREEFALL: stateStr = "FREEFALL"; break;
    case IMPACT:   stateStr = "IMPACT";   break;
    case FALLEN:   stateStr = "FALLEN";   break;
    default:       stateStr = "NORMAL";   break;
  }
  if (manualFall) stateStr = "FALLEN";

  // ── Buzzer ────────────────────────────────────────────────────
  updateBuzzer(fallen, gasAlert);

  // ── Serial output ─────────────────────────────────────────────
  // ax,ay,az,gx,gy,gz,pitch,roll,accelMag,gyroMag,fall,tilt,dist,state,gas,helmet
  Serial.print(ax, 3);           Serial.print(',');
  Serial.print(ay, 3);           Serial.print(',');
  Serial.print(az, 3);           Serial.print(',');
  Serial.print(gx, 1);           Serial.print(',');
  Serial.print(gy, 1);           Serial.print(',');
  Serial.print(gz, 1);           Serial.print(',');
  Serial.print(pitch, 1);        Serial.print(',');
  Serial.print(roll, 1);         Serial.print(',');
  Serial.print(accelMag, 3);     Serial.print(',');
  Serial.print(gyroMag, 1);      Serial.print(',');
  Serial.print(fallen ? 1 : 0);  Serial.print(',');
  Serial.print(tiltDir);         Serial.print(',');
  Serial.print(dist);            Serial.print(',');
  Serial.print(stateStr);        Serial.print(',');
  Serial.print(gasValue);        Serial.print(',');
  Serial.println(helmetOn ? 1 : 0);

  delay(50);  // 20 Hz
}
