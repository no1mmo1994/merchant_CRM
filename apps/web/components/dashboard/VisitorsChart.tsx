"use client";

import { motion } from "framer-motion";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { fadeUp } from "@/lib/animations/variants";
import { EmptyState } from "@/components/feedback/EmptyState";

/**
 * VisitorsChart — removed placeholder data (mobileShare=61,
 * desktopShare=27, etc. used to be hard-coded). Renders an empty
 * state until a real "sessions / device split" KPI endpoint is
 * available from the backend.
 */
export function VisitorsChart() {
  return (
    <motion.div variants={fadeUp} className="lg:col-span-4">
      <Card className="border-(--color-border)">
        <CardHeader>
          <CardTitle>Tổng lượt truy cập</CardTitle>
        </CardHeader>
        <CardContent>
          <EmptyState
            title="Chưa có dữ liệu lượt truy cập"
            description="Số liệu lượt truy cập theo thiết bị (mobile/desktop) sẽ hiển thị khi backend cung cấp endpoint analytics."
          />
        </CardContent>
      </Card>
    </motion.div>
  );
}
