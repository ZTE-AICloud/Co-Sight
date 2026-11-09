// SPDX-License-Identifier: Apache-2.0
/** @type {import('tailwindcss').Config} */
import plugin from "tailwindcss/plugin";

export default {
  darkMode: "class",
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        surface: {
          0: "rgb(var(--surface-0) / <alpha-value>)",
          1: "rgb(var(--surface-1) / <alpha-value>)",
          2: "rgb(var(--surface-2) / <alpha-value>)",
          3: "rgb(var(--surface-3) / <alpha-value>)",
          4: "rgb(var(--surface-4) / <alpha-value>)",
          5: "rgb(var(--surface-5) / <alpha-value>)",
        },
        border: {
          DEFAULT: "rgb(var(--border) / <alpha-value>)",
          light: "rgb(var(--border-light) / <alpha-value>)",
        },
        accent: {
          DEFAULT: "rgb(var(--accent) / <alpha-value>)",
          hover: "rgb(var(--accent-hover) / <alpha-value>)",
          muted: "rgba(99, 102, 241, 0.15)",
        },
        primary: "rgb(var(--text-primary) / <alpha-value>)",
        secondary: "rgb(var(--text-secondary) / <alpha-value>)",
        tertiary: "rgb(var(--text-tertiary) / <alpha-value>)",
        muted: "rgb(var(--text-muted) / <alpha-value>)",
        faint: "rgb(var(--text-faint) / <alpha-value>)",
      },
      fontFamily: {
        sans: [
          "Geist",
          "ui-sans-serif",
          "system-ui",
          "-apple-system",
          "BlinkMacSystemFont",
          "Segoe UI",
          "sans-serif",
        ],
        mono: [
          "Geist Mono",
          "JetBrains Mono",
          "Fira Code",
          "ui-monospace",
          "Consolas",
          "monospace",
        ],
      },
      animation: {
        "pulse-slow": "pulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
        "fade-in": "fadeIn 0.4s cubic-bezier(0.16, 1, 0.3, 1)",
        "slide-up": "slideUp 0.5s cubic-bezier(0.32, 0.72, 0, 1)",
        "slide-down": "slideDown 0.4s cubic-bezier(0.32, 0.72, 0, 1)",
        "shimmer": "shimmer 2.4s linear infinite",
        "glow-pulse": "glowPulse 3s cubic-bezier(0.4, 0, 0.6, 1) infinite",
      },
      keyframes: {
        fadeIn: {
          "0%": { opacity: "0" },
          "100%": { opacity: "1" },
        },
        slideUp: {
          "0%": { opacity: "0", transform: "translateY(12px) scale(0.98)" },
          "100%": { opacity: "1", transform: "translateY(0) scale(1)" },
        },
        slideDown: {
          "0%": { opacity: "0", transform: "translateY(-8px)" },
          "100%": { opacity: "1", transform: "translateY(0)" },
        },
        shimmer: {
          "0%": { backgroundPosition: "-200% 0" },
          "100%": { backgroundPosition: "200% 0" },
        },
        glowPulse: {
          "0%, 100%": { boxShadow: "0 0 0 0 rgba(168, 162, 255, 0.4)" },
          "50%": { boxShadow: "0 0 0 6px rgba(168, 162, 255, 0)" },
        },
      },
    },
  },
  plugins: [
    plugin(({ addUtilities, matchUtilities, theme }) => {
      // Fill utilities for SVG (primary / secondary / tertiary / muted / faint)
      matchUtilities(
        {
          fill: (value) => ({ fill: value }),
        },
        {
          values: {
            primary: `rgb(${theme("colors.primary")})`,
            secondary: `rgb(${theme("colors.secondary")})`,
            tertiary: `rgb(${theme("colors.tertiary")})`,
            muted: `rgb(${theme("colors.muted")})`,
            faint: `rgb(${theme("colors.faint")})`,
          },
        }
      );

      // Stroke utilities for SVG
      matchUtilities(
        {
          stroke: (value) => ({ stroke: value }),
        },
        {
          values: {
            primary: `rgb(${theme("colors.primary")})`,
            secondary: `rgb(${theme("colors.secondary")})`,
            tertiary: `rgb(${theme("colors.tertiary")})`,
            muted: `rgb(${theme("colors.muted")})`,
            faint: `rgb(${theme("colors.faint")})`,
          },
        }
      );

      // Border color utilities
      matchUtilities(
        {
          border: (value) => ({
            borderColor: value,
          }),
        },
        {
          values: {
            primary: `rgb(${theme("colors.primary")})`,
            secondary: `rgb(${theme("colors.secondary")})`,
            tertiary: `rgb(${theme("colors.tertiary")})`,
            muted: `rgb(${theme("colors.muted")})`,
            faint: `rgb(${theme("colors.faint")})`,
          },
        }
      );
    }),
  ],
};
