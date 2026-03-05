"use client"

import Image from "next/image"
import { cn } from "@/lib/utils"

export function ChristinaAvatar({
  size = "md",
  className,
}: {
  size?: "sm" | "md" | "lg" | "xl"
  className?: string
}) {
  const sizes = {
    sm: "h-7 w-7",
    md: "h-9 w-9",
    lg: "h-10 w-10",
    xl: "h-14 w-14",
  }
  const px = { sm: 28, md: 36, lg: 40, xl: 56 }

  return (
    <Image
      src="/christina-avatar.jpeg"
      alt="Christina"
      width={px[size]}
      height={px[size]}
      className={cn("shrink-0 rounded-full object-cover", sizes[size], className)}
    />
  )
}
