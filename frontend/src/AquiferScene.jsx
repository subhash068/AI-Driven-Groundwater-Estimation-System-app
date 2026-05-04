import React, { memo, useMemo, useState, useRef, useEffect } from "react";
import { Canvas, useFrame } from "@react-three/fiber";
import { Float, Text, ContactShadows, PresentationControls, Environment, Html } from "@react-three/drei";
import * as THREE from "three";

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

/**
 * Premium 3D Stratification Core
 * Visualizes the vertical geological profile of a village.
 */
const StratificationCore = memo(({ weatheredDepth, fracturedDepth, dtw, elevation }) => {
  // Normalize values for 3D scene scaling
  const wDepth = clamp(Number(weatheredDepth) || 12, 5, 40);
  const fDepth = clamp(Number(fracturedDepth) || 20, 10, 60);
  const waterLevel = clamp(Number(dtw) || 15, 2, wDepth + fDepth);
  const totalDepth = wDepth + fDepth;

  // Materials (Memoized to prevent memory leak and context loss)
  // Materials (Memoized to prevent memory leak and context loss)
  const materials = useMemo(() => {
    const soil = new THREE.MeshStandardMaterial({ color: "#8B5E34", roughness: 0.8, metalness: 0.1 });
    const weathered = new THREE.MeshStandardMaterial({ color: "#D2B48C", transparent: true, opacity: 0.85 });
    const fractured = new THREE.MeshStandardMaterial({ color: "#4A4A4A", roughness: 1.0 });
    const water = new THREE.MeshPhysicalMaterial({
      color: "#00e5ff",
      transparent: true,
      opacity: 0.6,
      transmission: 0.5,
      roughness: 0,
      metalness: 0.1,
      ior: 1.33,
      thickness: 0.5,
    });
    return { soil, weathered, fractured, water };
  }, []);

  // Cleanup effect
  useEffect(() => {
    return () => {
      Object.values(materials).forEach(m => m.dispose());
    };
  }, [materials]);

  // Calculate positions (Y is up)
  // Ground is at Y = 0
  const weatheredY = -wDepth / 2;
  const fracturedY = -wDepth - fDepth / 2;
  const waterY = -waterLevel;

  return (
    <group position={[0, totalDepth / 4, 0]}>
      {/* 1. Ground Surface / Topsoil */}
      <mesh position={[0, 0.1, 0]}>
        <cylinderGeometry args={[2.5, 2.5, 0.2, 32]} />
        <meshStandardMaterial color="#22c55e" />
      </mesh>

      {/* 2. Weathered Zone */}
      <mesh position={[0, weatheredY, 0]}>
        <cylinderGeometry args={[2.4, 2.4, wDepth, 32]} />
        <primitive object={materials.weathered} attach="material" />
      </mesh>

      {/* 3. Fractured Zone */}
      <mesh position={[0, fracturedY, 0]}>
        <cylinderGeometry args={[2.4, 2.4, fDepth, 32]} />
        <primitive object={materials.fractured} attach="material" />
      </mesh>

      {/* 4. Dynamic Water Table (Pulsing Layer) */}
      <Float speed={2} rotationIntensity={0.1} floatIntensity={0.2}>
        <mesh position={[0, waterY, 0]} rotation={[-Math.PI / 2, 0, 0]}>
          <circleGeometry args={[2.6, 32]} />
          <primitive object={materials.water} attach="material" />
          {/* Water Table Label */}
          <Html position={[2.8, 0, 0]} center>
            <div style={{ 
              background: 'rgba(0, 229, 255, 0.1)', 
              backdropFilter: 'blur(4px)',
              border: '1px solid rgba(0, 229, 255, 0.3)',
              padding: '2px 8px',
              borderRadius: '4px',
              color: '#00e5ff',
              fontSize: '10px',
              whiteSpace: 'nowrap',
              fontWeight: 'bold',
              pointerEvents: 'none'
            }}>
              Water Table: {waterLevel.toFixed(1)}m
            </div>
          </Html>
        </mesh>
      </Float>

      {/* 5. Depth Rulers */}
      <group position={[-3, 0, 0]}>
        {[0, -10, -20, -30, -40, -50].map((d) => (
          <group key={d} position={[0, d, 0]}>
            <mesh rotation={[0, 0, Math.PI / 2]}>
              <boxGeometry args={[0.05, 0.5, 0.05]} />
              <meshBasicMaterial color="#94a3b8" />
            </mesh>
            <Text
              position={[-0.8, 0, 0]}
              fontSize={0.4}
              color="#94a3b8"
              anchorX="right"
            >
              {Math.abs(d)}m
            </Text>
          </group>
        ))}
      </group>

      {/* Lithology Labels */}
      <Html position={[3, weatheredY, 0]} center>
        <div style={{ color: '#D2B48C', fontSize: '11px', fontWeight: 600 }}>Weathered Aquifer</div>
      </Html>
      <Html position={[3, fracturedY, 0]} center>
        <div style={{ color: '#94a3b8', fontSize: '11px', fontWeight: 600 }}>Fractured Bedrock</div>
      </Html>
    </group>
  );
});

export default function AquiferScene({ weatheredDepth, fracturedDepth, dtw, elevation }) {
  return (
    <div style={{ width: "100%", height: "100%", background: "#050b14", position: 'relative' }}>
      <ErrorBoundary fallback={<div style={{ padding: '20px', color: '#94a3b8', fontSize: '0.8rem', textAlign: 'center', background: '#0a101f', borderRadius: '12px', height: '100%', display: 'flex', alignItems: 'center', justifyContent: 'center' }}>3D View temporarily unavailable. GPU resources exhausted.</div>}>
        <Canvas
        camera={{ position: [8, 5, 12], fov: 45 }}
        gl={{ antialias: true, alpha: true, powerPreference: "low-power" }}
        shadows
        frameloop="demand"
      >
        <color attach="background" args={["#050b14"]} />
        <ambientLight intensity={0.5} />
        <pointLight position={[10, 10, 10]} intensity={1} />
        <spotLight position={[-10, 15, 10]} angle={0.3} penumbra={1} intensity={2} castShadow />

        <PresentationControls
          global
          config={{ mass: 2, tension: 500 }}
          snap={{ mass: 4, tension: 1500 }}
          rotation={[0, 0.3, 0]}
          polar={[-Math.PI / 3, Math.PI / 3]}
          azimuth={[-Math.PI / 1.4, Math.PI / 1.4]}
        >
          <StratificationCore
            weatheredDepth={weatheredDepth}
            fracturedDepth={fracturedDepth}
            dtw={dtw}
            elevation={elevation}
          />
        </PresentationControls>

        <ContactShadows position={[0, -15, 0]} opacity={0.4} scale={20} blur={2} far={4.5} />
        <Environment preset="city" />
      </Canvas>
      </ErrorBoundary>
    </div>
  );
}

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { hasError: false };
  }
  static getDerivedStateFromError(error) {
    return { hasError: true };
  }
  componentDidCatch(error, errorInfo) {
    console.error("3D Scene Error:", error, errorInfo);
  }
  render() {
    if (this.state.hasError) return this.props.fallback;
    return this.props.children;
  }
}
