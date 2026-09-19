"use client";
import { useCallback, useEffect, useState, useRef, ReactNode, MouseEvent } from "react";
import { useDropzone } from "react-dropzone";
import { toast } from "sonner";
import { usePaperStore } from "@/stores/paper-store";
import { cn } from "@/lib/utils";
import type { PaperInfo } from "@/types";

// 跨实例上传守卫：顶栏和空态会同时挂载两个 UploadButton，
// uploadingRef 是每实例的，A 实例上传中 B 实例的守卫读到的仍是 false。
// 用模块级标志保证"全局同时只有一个上传"（与后端昂贵的解析资源匹配）。
let globalUploading = false;

// 与后端 ALLOWED_FILE_EXTENSIONS / MAX_UPLOAD_SIZE_BYTES 保持一致
const ALLOWED_EXTENSIONS = [".pdf", ".docx"];
const MAX_UPLOAD_SIZE_BYTES = 50 * 1024 * 1024;

interface Props {
  children: ReactNode;
  onUploaded?: (paper: PaperInfo) => void;
}

export function UploadButton({ children, onUploaded }: Props) {
  const upload = usePaperStore((s) => s.upload);
  const [uploading, setUploading] = useState(false);
  const [progress, setProgress] = useState(0);
  // W1-01 §5.2 上传阶段文案：上传中 → 解析中 → 完成
  const [phase, setPhase] = useState<"idle" | "uploading" | "parsing" | "done">("idle");
  // 防止文件选择器双开：open() 触发的 input.click 会冒泡到父 div 再触发一次 open()
  const openingRef = useRef(false);
  // F9: uploading 的 ref 镜像——异步 onDrop 拿到的 uploading 闭包值可能过期；
  // 用 ref 保证守卫读到的是最新值
  const uploadingRef = useRef(false);
  // phase 复位定时器：卸载/重新上传时清掉，避免卸载后空转 setState
  const phaseTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // P2-4：当前上传的 AbortController——「取消」按钮 abort 它，api.upload 会以
  // 「上传已取消」reject，onDrop 的 catch 据此与真实失败区分开
  const abortRef = useRef<AbortController | null>(null);
  useEffect(() => () => {
    if (phaseTimerRef.current) clearTimeout(phaseTimerRef.current);
  }, []);

  // P2-4：取消当前上传（拖拽与按钮共用 onDrop → 同一条上传链路，天然都可取消）。
  // 取消后 finally 复位 uploadingRef / globalUploading，UI 立即回到可重新上传状态。
  // 注意：后端解析阶段（phase === "parsing"）取消只中止浏览器请求，
  // 服务端可能已完成解析并入库，属可接受取舍（前端不再等待即可）。
  const cancelUpload = useCallback(() => {
    abortRef.current?.abort();
  }, []);

  const onDrop = useCallback(async (files: File[]) => {
    // F9: 上传进行中直接忽略（拖拽新文件不受按钮 disabled 限制，需要这里兜底）。
    // 实例内 ref + 跨实例模块级标志双重检查
    if (uploadingRef.current || globalUploading) return;
    const file = files[0];
    if (!file) return;
    // 校验后缀（与后端 ALLOWED_EXTENSIONS 保持一致：.pdf / .docx）
    const lower = file.name.toLowerCase();
    const lastDot = lower.lastIndexOf(".");
    const suffix = lastDot >= 0 ? lower.slice(lastDot) : "";
    if (!ALLOWED_EXTENSIONS.includes(suffix)) {
      toast.error("仅支持 PDF / DOCX 文件");
      return;
    }
    if (file.size > MAX_UPLOAD_SIZE_BYTES) {
      toast.error("文件超过 50MB");
      return;
    }

    // F9: state + ref 同步置位（ref 供 onDrop 守卫读取，避开 setState 异步批处理的间隙）
    uploadingRef.current = true;
    globalUploading = true;
    setUploading(true);
    setProgress(0);
    setPhase("uploading");
    // P2-4：登记本次上传的控制器，供「取消」按钮中止
    const controller = new AbortController();
    abortRef.current = controller;
    try {
      const data = await upload(file, {
        signal: controller.signal,
        onProgress: (loaded, total) => {
          if (total > 0) {
            // 上传进度占 0-95%（留 5% 给后端解析）
            setProgress(Math.min(95, Math.round((loaded / total) * 95)));
            // 文件体已传完（loaded >= total）→ 后端正在解析
            if (loaded >= total) setPhase("parsing");
          }
        },
      });
      setProgress(100);
      setPhase("done");
      toast.success(`上传成功：${data.title || file.name} (${data.pages} 页)`);
      onUploaded?.(data);
    } catch (e: unknown) {
      // P2-4：用户主动取消不是错误——温和提示，不走 error toast
      if (controller.signal.aborted) {
        toast.message("已取消上传");
      } else {
        const msg = e instanceof Error ? e.message : String(e);
        toast.error(`上传失败：${msg}`);
      }
    } finally {
      abortRef.current = null;
      uploadingRef.current = false;
      globalUploading = false;
      setUploading(false);
      setProgress(0);
      // 短暂展示"完成"后复位（先清掉可能残留的上一个定时器）
      if (phaseTimerRef.current) clearTimeout(phaseTimerRef.current);
      phaseTimerRef.current = setTimeout(() => setPhase("idle"), 1500);
    }
  }, [upload, onUploaded]);

  const { getRootProps, getInputProps, isDragActive, open } = useDropzone({
    onDrop,
    // F9: 上传中禁用 dropzone（阻止拖拽/选择新文件进入排队）
    disabled: uploading,
    accept: {
      "application/pdf": [".pdf"],
      "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
    },
    multiple: false,
    noClick: true,
  });

  // 防双触发：
  // 1. 正在上传时禁用按钮（视觉 + 功能）
  // 2. 阻止冒泡：open() 会触发 input.click，input.click 冒泡到父 div 又会触发 onClick
  // 3. 用 ref 锁 + stopPropagation 双重保险
  const handleClick = (e: MouseEvent) => {
    e.stopPropagation();
    if (uploading || openingRef.current) return;
    openingRef.current = true;
    open();
    // 重置锁（500ms 后允许重新打开；文件选择器弹出/关闭足够）
    setTimeout(() => {
      openingRef.current = false;
    }, 500);
  };

  return (
    <div {...getRootProps()} className="relative" onClick={(e) => e.stopPropagation()}>
      <input {...getInputProps()} />
      <div
        onClick={handleClick}
        className={cn("cursor-pointer", uploading && "pointer-events-none opacity-60")}
        aria-disabled={uploading}
      >
        {children}
      </div>
      {(uploading || phase === "done") && (
        <div className="absolute -bottom-1 left-0 right-0">
          <div className="h-1 bg-primary/20 rounded overflow-hidden">
            <div className="h-full bg-primary transition-all" style={{ width: `${progress}%` }} />
          </div>
          <div
            className="text-[10px] text-muted-foreground mt-0.5 text-center relative"
            role="status"
            aria-live="polite"
          >
            {phase === "uploading" && `上传中 ${progress}%`}
            {phase === "parsing" && "解析中…"}
            {phase === "done" && "解析完成"}
            {/* P2-4：上传/解析请求进行中可取消（解析完成 done 态无请求可取消） */}
            {uploading && (
              <button
                type="button"
                onClick={(e) => {
                  e.stopPropagation();
                  cancelUpload();
                }}
                className="absolute right-0 top-1/2 -translate-y-1/2 underline underline-offset-2 hover:text-foreground"
              >
                取消
              </button>
            )}
          </div>
        </div>
      )}
      {isDragActive && (
        <div className="fixed inset-0 z-50 bg-background/80 border-4 border-dashed border-[hsl(var(--cinnabar))] flex items-center justify-center pointer-events-none">
          <div className="text-center">
            <div className="font-display text-2xl font-semibold text-foreground">松手，放上书架</div>
            <div className="text-xs text-muted-foreground mt-2">支持 PDF 与 Word，50MB 以内</div>
          </div>
        </div>
      )}
    </div>
  );
}
