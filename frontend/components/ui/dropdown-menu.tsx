"use client";

import * as React from "react";
import * as Primitive from "@radix-ui/react-dropdown-menu";
export const DropdownMenu = Primitive.Root;
export const DropdownMenuTrigger = Primitive.Trigger;
export const DropdownMenuItem = Primitive.Item;
export const DropdownMenuSeparator = Primitive.Separator;
export const DropdownMenuContent = React.forwardRef<React.ElementRef<typeof Primitive.Content>, React.ComponentPropsWithoutRef<typeof Primitive.Content>>((props, ref) => <Primitive.Portal><Primitive.Content ref={ref} collisionPadding={12} {...props} /></Primitive.Portal>);
DropdownMenuContent.displayName = "DropdownMenuContent";
