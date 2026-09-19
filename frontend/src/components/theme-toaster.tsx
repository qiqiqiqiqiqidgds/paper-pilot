"use client";
/**
 * 跟随主题的 Toaster（对齐 app.html #toast：底部居中墨色圆角条）
 * sonner 的 <Toaster> 默认 theme="light" 且不会跟随 next-themes 的 .dark class，
 * 直接放在 RootLayout 会让暗色用户看到亮底 toast。
 */
import { useTheme } from "next-themes";
import { Toaster } from "sonner";

export function ThemeToaster() {
  const { resolvedTheme } = useTheme();
  return (
    <Toaster
      position="bottom-center"
      closeButton
      theme={resolvedTheme === "dark" ? "dark" : "light"}
      toastOptions={{
        style: {
          background: "hsl(var(--foreground))",
          color: "hsl(var(--background))",
          border: "none",
          borderRadius: "6px",
          fontSize: "12.5px",
        },
      }}
    />
  );
}
