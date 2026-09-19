"use client";
import * as React from "react";
import { Slot } from "@radix-ui/react-slot";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

/* 「批注手稿」按钮（对齐 app.html .btn 规格）：
   墨底纸字主按钮 / 纸底细线描边次按钮；无投影，层次靠边线 */
const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 whitespace-nowrap rounded text-[12.5px] transition-colors focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-45",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground font-semibold hover:bg-primary-hover border border-primary",
        outline: "border border-input bg-card text-ink2 hover:border-border-strong hover:text-foreground",
        ghost: "border border-border bg-card text-ink2 hover:border-border-strong hover:text-foreground",
        secondary: "bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive: "bg-destructive text-destructive-foreground hover:bg-destructive/90",
      },
      size: {
        default: "h-[30px] px-3",
        sm: "h-7 rounded px-2.5 text-xs",
        lg: "h-10 rounded px-8",
        icon: "h-[30px] w-[30px] p-0 justify-center",
      },
    },
    defaultVariants: { variant: "default", size: "default" },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, type, ...props }, ref) => {
    const Comp = asChild ? Slot : "button";
    // P3-5: 默认 type="button"，避免 form 内意外提交
    // asChild 时让 Slot 子元素自己控制 type
    return <Comp className={cn(buttonVariants({ variant, size, className }))} ref={ref} type={asChild ? type : type ?? "button"} {...props} />;
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
