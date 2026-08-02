"use client";

import { useState } from "react";
import { motion } from "framer-motion";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { fadeUp } from "@/lib/animations/variants";
import { EmptyState } from "@/components/feedback/EmptyState";
import { formatVND } from "@/lib/data/placeholder-kpis";

type Tab = "overview" | "forecasting" | "trends";

/**
 * Sales performance line chart.
 *
 * Bug fix #6: v1 used `placeholderSalesPerformance` (a hand-tuned sin
 * wave). That's been removed — instead the chart renders an honest
 * empty state until the backend exposes a real sales-per-month KPI.
 */
export function SalesPerformanceChart() {
  const [tab, setTab] = useState<Tab>("overview");

  return (
    <motion.div variants={fadeUp} className="lg:col-span-8">
      <Card className="border-(--color-border)">
        <CardHeader className="flex flex-row items-center justify-between space-y-0">
          <CardTitle>Hiệu quả kinh doanh</CardTitle>
          <Tabs value={tab} onValueChange={(v) => setTab(v as Tab)}>
            <TabsList>
              <TabsTrigger value="overview">Tổng quan</TabsTrigger>
              <TabsTrigger value="forecasting">Dự báo</TabsTrigger>
              <TabsTrigger value="trends">Xu hướng</TabsTrigger>
            </TabsList>
          </Tabs>
        </CardHeader>
        <CardContent>
          <div className="rounded-lg border border-dashed border-(--color-border) p-8">
            <EmptyState
              title="Chưa có dữ liệu hiệu quả kinh doanh"
              description="Biểu đồ doanh thu / chi phí sẽ hiển thị khi backend cung cấp endpoint KPI theo tháng. Hiện tại không có dữ liệu thật để hiển thị."
            />
          </div>

          <div className="mt-4 flex items-center gap-4 text-sm opacity-60">
            <span className="inline-flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-[#F26B3A]" />
              <span className="text-(--color-muted-foreground)">Doanh thu</span>
            </span>
            <span className="inline-flex items-center gap-2">
              <span className="h-2.5 w-2.5 rounded-full bg-[#3B82F6]" />
              <span className="text-(--color-muted-foreground)">Chi phí</span>
            </span>
          </div>
        </CardContent>
      </Card>
    </motion.div>
  );
}

// Suppress unused warning while keeping the helper import for future
// real-KPI rendering.
void formatVND;
