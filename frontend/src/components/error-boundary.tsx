"use client";
import React, { Component, ErrorInfo, ReactNode } from "react";
import { AlertCircle, RefreshCw } from "lucide-react";
import { Button } from "./ui/button";

interface Props {
  children: ReactNode;
  /** 自定义 fallback（默认带错误信息 + 重试按钮） */
  fallback?: (error: Error, reset: () => void) => ReactNode;
  /**
   * 复位键：变化时自动清除错误态（React 官方推荐的 resetKey 模式）。
   * 等价于给本组件加 React key 触发重挂载的旧行为，但**不卸载子树**——
   * 对包含 next/dynamic 懒加载子组件（如 PDFViewer）的边界，keyed 重挂载
   * 会使旧 <main> 宿主节点残留为孤儿并在 DOM 中不断累积（P0 缺陷），
   * 因此所有"切论文复位错误边界"的场景必须用本 prop 而不是 key。
   */
  resetKey?: string | null;
}

interface State {
  hasError: boolean;
  error: Error | null;
  prevResetKey?: string | null;
}

/**
 * 全局 Error Boundary（P1-22）
 *
 * 用法：
 *   <ErrorBoundary>
 *     <AIAnalysisPanel />
 *   </ErrorBoundary>
 *
 * 仅捕获子组件渲染/生命周期异常，不捕获事件处理器内异常。
 * 事件处理器内 try/catch 仍然需要手动。
 */
export class ErrorBoundary extends Component<Props, State> {
  constructor(props: Props) {
    super(props);
    this.state = { hasError: false, error: null };
  }

  static getDerivedStateFromError(error: Error): State {
    return { hasError: true, error };
  }

  // resetKey 变化 → 复位错误态（不重挂载子树，见 Props.resetKey 注释）
  static getDerivedStateFromProps(props: Props, state: State): Partial<State> | null {
    if (state.prevResetKey !== props.resetKey) {
      return { prevResetKey: props.resetKey, hasError: false, error: null };
    }
    return null;
  }

  componentDidCatch(error: Error, errorInfo: ErrorInfo) {
    // 详细错误上报到 console（生产可对接 Sentry 等）
    console.error("[ErrorBoundary] 捕获到错误:", error, errorInfo);
  }

  reset = () => {
    this.setState({ hasError: false, error: null });
  };

  render() {
    if (this.state.hasError && this.state.error) {
      if (this.props.fallback) {
        return this.props.fallback(this.state.error, this.reset);
      }
      return (
        <div className="flex flex-col items-center justify-center h-full p-6 text-center">
          <AlertCircle className="h-10 w-10 text-destructive mb-3" />
          <div className="text-base font-medium mb-1">页面出错了</div>
          <div className="text-sm text-muted-foreground mb-4 max-w-md break-all">
            {this.state.error.message || "未知错误"}
          </div>
          <Button size="sm" variant="default" onClick={this.reset}>
            <RefreshCw className="h-3 w-3 mr-1" />重试
          </Button>
          <div className="text-xs text-muted-foreground mt-4">
            如果问题持续，请刷新页面或联系管理员
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}