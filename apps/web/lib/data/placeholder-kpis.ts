/**
 * Deterministic placeholder data for the dashboard. Generated server-side
 * from a fixed seed so SSR and client hydration don't fight.
 *
 * Real production data will replace these via phases 11/12 (sync jobs).
 */

export interface MonthlyPoint {
  month: string;
  sales: number;
  costs: number;
}

export interface OrderRow {
  id: string;
  product: string;
  sale: number;
  order: number;
  conversionRate: number;
  price: number;
  status: "completed" | "pending" | "refunded";
}

export interface DashboardKPIs {
  totalRevenue: number;
  revenueChange: number; // percent
  sales: number;
  salesChange: number;
  dailyAverage: number;
  dailyAverageChange: number;
  newCustomers: number;
  newCustomersChange: number;
  totalOrders: number;
  totalOrdersChange: number;
  totalVisitors: number;
  visitorsChange: number;
  mobileShare: number;
  desktopShare: number;
  mobileChange: number;
  desktopChange: number;
}

export const placeholderKPIs: DashboardKPIs = {
  totalRevenue: 858_198.46,
  revenueChange: 12.4,
  sales: 248_756,
  salesChange: 8.2,
  dailyAverage: 12_437,
  dailyAverageChange: 4.1,
  newCustomers: 1_842,
  newCustomersChange: 6.7,
  totalOrders: 7_321,
  totalOrdersChange: -2.3,
  totalVisitors: 237_456,
  visitorsChange: 3.2,
  mobileShare: 61,
  desktopShare: 27,
  mobileChange: 0.8,
  desktopChange: 0.8,
};

const months = [
  "Jan",
  "Feb",
  "Mar",
  "Apr",
  "May",
  "Jun",
  "Jul",
  "Aug",
  "Sep",
  "Oct",
  "Nov",
  "Dec",
];

export const placeholderSalesPerformance: MonthlyPoint[] = months.map((month, i) => {
  // Hand-tuned sin curves so the chart looks organic but reproducible.
  const phase = (i / 12) * Math.PI * 2;
  const sales = Math.round(48_000 + Math.sin(phase) * 14_000 + (i * 1_200));
  const costs = Math.round(28_000 + Math.cos(phase) * 8_000 + (i * 600));
  return { month, sales, costs };
});

export const placeholderOrders: OrderRow[] = [
  { id: "ORD-7821", product: "Phở Bò Tái", sale: 128, order: 92, conversionRate: 71.9, price: 75_000, status: "completed" },
  { id: "ORD-7822", product: "Bún Chả Hà Nội", sale: 96, order: 71, conversionRate: 73.9, price: 65_000, status: "completed" },
  { id: "ORD-7823", product: "Cà Phê Sữa Đá", sale: 245, order: 220, conversionRate: 89.8, price: 29_000, status: "completed" },
  { id: "ORD-7824", product: "Bánh Mì Thịt Nướng", sale: 312, order: 280, conversionRate: 89.7, price: 35_000, status: "pending" },
  { id: "ORD-7825", product: "Cơm Tấm Sườn Bì", sale: 88, order: 65, conversionRate: 73.9, price: 85_000, status: "completed" },
  { id: "ORD-7826", product: "Trà Đào Cam Sả", sale: 178, order: 162, conversionRate: 91.0, price: 39_000, status: "completed" },
  { id: "ORD-7827", product: "Bánh Xèo Miền Tây", sale: 54, order: 38, conversionRate: 70.4, price: 95_000, status: "refunded" },
  { id: "ORD-7828", product: "Hủ Tiếu Nam Vang", sale: 112, order: 90, conversionRate: 80.4, price: 70_000, status: "completed" },
  { id: "ORD-7829", product: "Chè Ba Màu", sale: 67, order: 58, conversionRate: 86.6, price: 25_000, status: "pending" },
  { id: "ORD-7830", product: "Gỏi Cuốn Tôm Thịt", sale: 145, order: 130, conversionRate: 89.7, price: 45_000, status: "completed" },
];

export function formatVND(value: number): string {
  return new Intl.NumberFormat("vi-VN", {
    style: "currency",
    currency: "VND",
    maximumFractionDigits: 0,
  }).format(value);
}

export function formatNumber(value: number): string {
  return new Intl.NumberFormat("en-US").format(value);
}

export function formatPercent(value: number): string {
  const sign = value > 0 ? "+" : value < 0 ? "" : "";
  return `${sign}${value.toFixed(1)}%`;
}
