import type { Metadata } from "next";
import { ThemeProvider } from "next-themes";
import { ThemeToaster } from "@/components/theme-toaster";
import "./globals.css";
import "./noto-serif-sc.css";

export const metadata: Metadata = {
  title: "PaperPilot - AI 论文伴读",
  description: "上传 PDF / Word，AI 自动拆解、对比、找漏洞、出 PPT",
  icons: { icon: "/favicon.svg" },
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="zh-CN" suppressHydrationWarning>
      <body className="h-full overflow-hidden">
        {/* 暗色模式：next-themes 管理 .dark class（本地/系统偏好） */}
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          {children}
          {/* ThemeToaster 是 client 组件：读取 resolvedTheme 让 toast 跟随暗色模式 */}
          <ThemeToaster />
        </ThemeProvider>
      </body>
    </html>
  );
}
