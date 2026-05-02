# Scientific-Grade Dashboard UI Design System

This system implements a production-grade, map-centric interface designed for scientific analysis and governmental decision-making.

## 🎨 Core Design Tokens

### Color Palette
- **Primary (Water)**: `#2563EB` (Blue)
- **Secondary (Sustainability)**: `#22C55E` (Green)
- **Danger (Depletion)**: `#EF4444` (Red)
- **Warning (Risk)**: `#FACC15` (Yellow)
- **Base Background**: `#0F172A` (Deep Slate)
- **Panel/Card Background**: `rgba(30, 41, 59, 0.7)` (Glassmorphism)

### Typography
- **Primary Font**: `Inter`, System UI Sans
- **Styles**: Optimized for high readability with distinct hierarchies for metrics and labels.

## 🧱 Layout Architecture

### 1. Global Wrapper (`.layout`)
- **Grid Strategy**: 3-column flex/grid (Sidebar | Map | Analytics).
- **Navigation Header**: Fixed top navbar for global filters and identity.

### 2. Glassmorphism Components
- **Backdrop Blur**: `16px` for cards and panels to provide depth without visual noise.
- **Borders**: Subtle `1px solid rgba(255, 255, 255, 0.08)` to define edges against dark backgrounds.

### 3. Interactions & Animations
- **Smooth Transitions**: `0.3s cubic-bezier(0.4, 0, 0.2, 1)` for all interactive elements.
- **Glow Effects**: Active navigation items feature a primary-color glow to indicate focus.
- **Slide-in Panels**: The Village Insight panel utilizes a hardware-accelerated transform for fluid right-to-left movement.

## 📱 Responsive Strategy
- **Desktop**: 3-pane layout for maximum data density.
- **Tablet**: Collapsible sidebar, sliding overlays for insights.
- **Mobile**: Vertical stack (Map → Insights → Analytics).

## 🚀 Future Enhancements
- **Theme Switching**: CSS Variable support ready for Light/Dark mode toggling.
- **Micro-interactions**: Particle effects for "Recharge Zones" on the map.
- **Lottie Integration**: Smooth loading animations for AI inference results.
