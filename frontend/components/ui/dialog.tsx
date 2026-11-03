"use client";

import * as React from "react";
import * as Primitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";

export const Dialog = Primitive.Root;
export const DialogTitle = Primitive.Title;
export const DialogDescription = Primitive.Description;
export const DialogContent = React.forwardRef<React.ElementRef<typeof Primitive.Content>, React.ComponentPropsWithoutRef<typeof Primitive.Content>>(({ children, className, ...props }, ref) => <Primitive.Portal>
  <Primitive.Overlay className="account-dialog-overlay" />
  <Primitive.Content ref={ref} className={`account-dialog-content ${className || ""}`} {...props}>{children}<Primitive.Close className="account-dialog-close" aria-label="Close account settings"><X size={18} /></Primitive.Close></Primitive.Content>
</Primitive.Portal>);
DialogContent.displayName = "DialogContent";
