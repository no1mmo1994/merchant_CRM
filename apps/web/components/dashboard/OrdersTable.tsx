"use client";

import * as React from "react";
import { motion } from "framer-motion";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Search } from "lucide-react";
import { fadeUp } from "@/lib/animations/variants";
import { EmptyState } from "@/components/feedback/EmptyState";

/**
 * Orders list — previously populated with `placeholderOrders` (fake
 * rows like "Phở Bò Tái / ORD-7821 / pending"). User complained those
 * looked like real data; they've been replaced with a real empty
 * state. When a backend `/api/orders` endpoint lands, this card will
 * be wired up against it.
 */
export function OrdersTable() {
  const [query, setQuery] = React.useState("");

  return (
    <motion.div variants={fadeUp} className="lg:col-span-12">
      <Card className="border-(--color-border)">
        <CardHeader className="flex flex-row items-center justify-between gap-4 space-y-0">
          <CardTitle>Danh sách đơn hàng</CardTitle>
          <div className="relative w-full max-w-sm">
            <Search className="pointer-events-none absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-(--color-muted-foreground)" />
            <Input
              className="h-9 pl-8"
              placeholder="Tìm đơn hàng, sản phẩm, trạng thái…"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              aria-label="Tìm đơn hàng"
              disabled
              title="Endpoint danh sách đơn hàng chưa được backend cung cấp"
            />
          </div>
        </CardHeader>
        <CardContent>
          <EmptyState
            title="Chưa có dữ liệu đơn hàng"
            description="Bảng đơn hàng sẽ hiển thị khi backend cung cấp endpoint /api/orders. Các dữ liệu trước đây hiển thị ở đây là dữ liệu demo và đã được loại bỏ."
          />
        </CardContent>
      </Card>
    </motion.div>
  );
}
