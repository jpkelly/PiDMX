#version 300 es
precision mediump float;

// Rainbow Rain Shader — 10x30 pixel grid

uniform float uTime;       // drive with absTime.seconds
uniform float uSpeed;      // default ~4.0 (pixels per second)
uniform int   uTrailLen;   // default 10 (pixels)
uniform float uDensity;    // default 3.0 (>=1: drops per column, <1: probability of a drop)
uniform float uActive;         // 1.0 = rain enabled, 0.0 = screen dark
uniform float uSpawnGateStart; // uTime when spawning started (-1.0 = no gate)
uniform float uSpawnGateStop;  // uTime when spawning stopped (-1.0 = no gate)

out vec4 fragColor;

// --- helpers ---------------------------------------------------------------
float hash(float n) { return fract(sin(n * 127.1) * 43758.5453123); }
float hash2(float a, float b) { return fract(sin(a * 127.1 + b * 311.7) * 43758.5453123); }

vec3 hsv2rgb(float h, float s, float v) {
    vec3 k = mod(vec3(h * 6.0, h * 6.0 - 2.0, h * 6.0 - 4.0), 6.0);
    return v * mix(vec3(1.0), clamp(2.0 - abs(k - 3.0), 0.0, 1.0), s);
}

void main()
{
    // Grid constants
    const int COLS = 10;
    const int ROWS = 30;

    float speed    = uSpeed > 0.0 ? uSpeed : 4.0;
    int   trailLen = uTrailLen > 0 ? uTrailLen : 10;
    float density  = uDensity  > 0.0 ? uDensity  : 3.0;

    // Screen is fully dark when inactive
    if (uActive < 0.5) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    // When density < 1, it's a probability each column has 1 drop
    // When density >= 1, it's the number of drops per column
    int numDrops = max(int(ceil(density)), 1);

    // Current pixel coordinate (integer) — use gl_FragCoord for exact pixel
    int col = int(gl_FragCoord.x);
    int row = int(gl_FragCoord.y);
    col = clamp(col, 0, COLS - 1);
    row = clamp(row, 0, ROWS - 1);

    vec3 color = vec3(0.0);

    // Extended virtual canvas: drops spawn trailLen rows above the visible screen
    // so they always enter fully-formed from the top edge, with no clipping.
    // cycle = ROWS + 2*trailLen  (off-screen buffer above + screen + exit buffer below)
    int cycle = ROWS + 2 * trailLen;

    // Virtual row for this fragment (0 = top of off-screen buffer, increases downward).
    // GL row ROWS-1 = top of visible screen  → virtual row trailLen
    // GL row 0      = bottom of visible screen → virtual row (trailLen + ROWS - 1)
    int fragVirtual = trailLen + ROWS - 1 - row;

    for (int d = 0; d < numDrops; ++d) {
        float seed  = hash2(float(col) + 0.5, float(d) + 0.5) * 1000.0;
        float rate  = 0.5 + 0.5 * hash(seed + 1.0);
        float phase = hash(seed + 2.0) * float(cycle);

        float totalProgress = phase + uTime * speed * rate;
        float cycleF        = floor(totalProgress / float(cycle));
        float headF         = totalProgress - cycleF * float(cycle);

        // Spawn gate: only show drops whose cycle started after activation.
        // Allow the current cycle if the drop's head was still in the off-screen
        // spawn buffer at the moment activation happened (about to enter screen).
        if (uSpawnGateStart >= 0.0) {
            float progressAtStart = phase + uSpawnGateStart * speed * rate;
            float cycleAtStart    = floor(progressAtStart / float(cycle));
            float headFAtStart    = progressAtStart - cycleAtStart * float(cycle);
            if (cycleF < cycleAtStart) continue;
            if (cycleF == cycleAtStart && headFAtStart >= float(trailLen)) continue;
        }

        // Spawn gate: suppress new cycles that started after deactivation;
        // in-flight drops at deactivation time continue until they exit naturally.
        if (uSpawnGateStop >= 0.0) {
            float progressAtStop = phase + uSpawnGateStop * speed * rate;
            float cycleAtStop    = floor(progressAtStop / float(cycle));
            if (cycleF > cycleAtStop) continue;
        }

        // Probabilistic density (density < 1.0): re-roll each cycle
        if (density < 1.0) {
            float roll = hash2(seed + 3.0, cycleF);
            if (roll > density) continue;
        }

        // Compute head/trail positions in virtual space (no wrap needed)
        int headVirtual = int(floor(headF));
        int dist        = fragVirtual - headVirtual;

        if (dist == 0) {
            color += vec3(1.0);  // white head pixel
        } else if (dist > 0 && dist <= trailLen) {
            float t          = float(dist) / float(trailLen);
            float hue        = fract(t + hash(seed));
            float saturation = 0.7 + 0.3 * (1.0 - t);
            float brightness = 1.0 - t * t;
            color           += hsv2rgb(hue, saturation, brightness);
        }
    }

    color = clamp(color, 0.0, 1.0);
    fragColor = vec4(color, 1.0);
}
