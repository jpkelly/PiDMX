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
    const int COLS = 10;
    const int ROWS = 30;

    float speed    = uSpeed > 0.0 ? uSpeed : 4.0;
    int   trailLen = uTrailLen > 0 ? uTrailLen : 10;
    float density  = uDensity  > 0.0 ? uDensity  : 3.0;

    // uActive=0: sensor mode not yet triggered — keep screen dark
    if (uActive < 0.5) {
        fragColor = vec4(0.0, 0.0, 0.0, 1.0);
        return;
    }

    int numDrops    = max(int(ceil(density)), 1);
    int col         = clamp(int(gl_FragCoord.x), 0, COLS - 1);
    int row         = clamp(int(gl_FragCoord.y), 0, ROWS - 1);

    vec3 color = vec3(0.0);

    // Virtual canvas (0 = top of spawn buffer, increases downward):
    //   0 .. trailLen-1          : off-screen spawn buffer above visible area
    //   trailLen .. trailLen+ROWS-1 : visible screen (GL row ROWS-1 → trailLen)
    //   trailLen+ROWS .. 2*trailLen+ROWS-1 : exit buffer below screen
    // Total cycle = ROWS + 2*trailLen so a spawned drop always exits cleanly.
    int cycleLen    = ROWS + 2 * trailLen;
    int fragVirtual = trailLen + ROWS - 1 - row;  // increases downward

    for (int d = 0; d < numDrops; ++d) {
        float seed     = hash2(float(col) + 0.5, float(d) + 0.5) * 1000.0;
        float rate     = 0.5 + 0.5 * hash(seed + 1.0);
        float phase    = hash(seed + 2.0) * float(cycleLen);
        float spdRate  = max(speed * rate, 0.001);

        float progress = phase + uTime * spdRate;
        float cycleIdx = floor(progress / float(cycleLen));
        float headF    = progress - cycleIdx * float(cycleLen);

        // Exact uTime when this drop cycle's head was at virtual row 0 (spawned)
        float tSpawn   = (cycleIdx * float(cycleLen) - phase) / spdRate;

        // Spawn gate — a cycle is shown only if it was spawned while sensor was active.
        // Any cycle that passes this check runs to completion, never interrupted.
        if (uSpawnGateStart >= 0.0 && tSpawn < uSpawnGateStart) continue;
        if (uSpawnGateStop  >= 0.0 && tSpawn > uSpawnGateStop)  continue;

        // Probabilistic density
        if (density < 1.0) {
            if (hash2(seed + 3.0, cycleIdx) > density) continue;
        }

        int headVirtual = int(floor(headF));

        // Rain falls downward: head is at headVirtual, trail extends ABOVE it.
        // Pixels above the head have a smaller row number → larger fragVirtual.
        // dist = headVirtual - fragVirtual > 0 means fragment is above the head.
        int dist = headVirtual - fragVirtual;

        if (dist == 0) {
            color += vec3(1.0);               // bright white head
        } else if (dist > 0 && dist <= trailLen) {
            float t   = float(dist) / float(trailLen);
            float hue = fract(t + hash2(seed, cycleIdx));  // new hue each cycle pass
            color    += hsv2rgb(hue, 1.0, smoothstep(1.0, 0.0, t));  // smooth ease to black
        }
    }

    color = clamp(color, 0.0, 1.0);
    fragColor = vec4(color, 1.0);
}
