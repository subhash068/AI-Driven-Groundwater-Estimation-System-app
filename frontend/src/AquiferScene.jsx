import React, { memo, useMemo, useState } from "react";
import { Canvas, useFrame } from "@react-three/fiber";

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function FallbackAquifer({ weatheredDepth, fracturedDepth }) {
  const weatheredPct = clamp((Number(weatheredDepth) / 30) * 100, 18, 72);
  const fracturedPct = clamp((Number(fracturedDepth) / 40) * 100, 20, 78);
  const waterPct = clamp(100 - weatheredPct - fracturedPct, 10, 30);

  return (
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "grid",
        gridTemplateRows: `${waterPct}% ${weatheredPct}% ${fracturedPct}%`,
        borderRadius: "8px",
        overflow: "hidden",
        background: "#0b1320",
      }}
      aria-label="Aquifer geometry fallback"
    >
      <div style={{ background: "linear-gradient(180deg,#7dd3fc,#38bdf8)" }} />
      <div style={{ background: "linear-gradient(180deg,#d6a97b,#b57f50)" }} />
      <div style={{ background: "linear-gradient(180deg,#7b8c9c,#5c6f7f)" }} />
    </div>
  );
}

const Stratification = memo(({ weatheredDepth, fracturedDepth }) => {
  const w = clamp(Number(weatheredDepth) || 10, 4, 30);
  const f = clamp(Number(fracturedDepth) || 18, 6, 40);

  return (
    <>
      <mesh position={[0, w / 5, 0]}>
        <boxGeometry args={[2.2, w / 2.4, 2.2]} />
        <meshStandardMaterial color="#b57f50" />
      </mesh>
      <mesh position={[0, -(f / 5), 0]}>
        <boxGeometry args={[2.4, f / 2.8, 2.4]} />
        <meshStandardMaterial color="#5c6f7f" />
      </mesh>
      <mesh rotation={[-Math.PI / 2, 0, 0]} position={[0, -2.2, 0]}>
        <planeGeometry args={[8, 8]} />
        <meshStandardMaterial color="#d8e6d2" />
      </mesh>
    </>
  );
});

function SlowRotate({ children }) {
  const groupRef = React.useRef(null);
  useFrame((_state, delta) => {
    if (!groupRef.current) return;
    groupRef.current.rotation.y += delta * 0.35;
  });
  return <group ref={groupRef}>{children}</group>;
}

export default function AquiferScene({ weatheredDepth, fracturedDepth }) {
  const [ready, setReady] = useState(false);
  const safeDepths = useMemo(
    () => ({
      weathered: clamp(Number(weatheredDepth) || 10, 4, 30),
      fractured: clamp(Number(fracturedDepth) || 18, 6, 40),
    }),
    [weatheredDepth, fracturedDepth]
  );

  return (
    <div style={{ width: "100%", height: "100%", position: "relative" }}>
      <Canvas
        camera={{ position: [4.2, 3.6, 5.8], fov: 52 }}
        gl={{ antialias: true, alpha: true }}
        onCreated={({ gl }) => {
          gl.setClearColor(0x000000, 0);
          setReady(true);
        }}
        onPointerMissed={() => {}}
      >
        <ambientLight intensity={0.75} />
        <directionalLight position={[3, 5, 2]} intensity={1.2} />
        <directionalLight position={[-2, 3, -2]} intensity={0.45} />
        <SlowRotate>
          <Stratification
            weatheredDepth={safeDepths.weathered}
            fracturedDepth={safeDepths.fractured}
          />
        </SlowRotate>
      </Canvas>

      {!ready && (
        <div style={{ position: "absolute", inset: 0 }}>
          <FallbackAquifer
            weatheredDepth={safeDepths.weathered}
            fracturedDepth={safeDepths.fractured}
          />
        </div>
      )}
    </div>
  );
}
