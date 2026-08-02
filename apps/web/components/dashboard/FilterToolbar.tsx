"use client";

import * as React from "react";
import { ArrowUpDown, Filter, CalendarDays } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuGroup,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";

/**
 * Three pill buttons that match the reference image's filter bar.
 *
 * Each button opens a real DropdownMenu so the visual contract is
 * accurate, even though the underlying state is intentionally inert in
 * v1 (placeholder dashboard).
 */
export function FilterToolbar() {
  return (
    <div className="flex flex-wrap items-center gap-2">
      <DropdownMenu>
        <DropdownMenuTrigger
          render={(props) => (
            <Button
              {...props}
              size="sm"
              variant="outline"
              className="h-8 gap-1.5"
              aria-label="Sắp xếp theo"
            >
              <ArrowUpDown className="h-3.5 w-3.5" />
              Sắp xếp
            </Button>
          )}
        />
        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Sắp xếp theo</DropdownMenuLabel>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem>Mới nhất</DropdownMenuItem>
          <DropdownMenuItem>Cũ nhất</DropdownMenuItem>
          <DropdownMenuItem>Doanh thu cao nhất</DropdownMenuItem>
          <DropdownMenuItem>Doanh thu thấp nhất</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <DropdownMenu>
        <DropdownMenuTrigger
          render={(props) => (
            <Button
              {...props}
              size="sm"
              variant="outline"
              className="h-8 gap-1.5"
              aria-label="Lọc"
            >
              <Filter className="h-3.5 w-3.5" />
              Lọc
            </Button>
          )}
        />
        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Lọc</DropdownMenuLabel>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem>Cửa hàng hoạt động</DropdownMenuItem>
          <DropdownMenuItem>Cửa hàng chờ duyệt</DropdownMenuItem>
          <DropdownMenuItem>Cửa hàng đóng cửa</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>

      <DropdownMenu>
        <DropdownMenuTrigger
          render={(props) => (
            <Button
              {...props}
              size="sm"
              variant="outline"
              className="h-8 gap-1.5"
              aria-label="Khoảng ngày"
            >
              <CalendarDays className="h-3.5 w-3.5" />
              30 ngày gần nhất
            </Button>
          )}
        />
        <DropdownMenuContent align="end" className="w-44">
          <DropdownMenuGroup>
            <DropdownMenuLabel>Khoảng ngày</DropdownMenuLabel>
          </DropdownMenuGroup>
          <DropdownMenuSeparator />
          <DropdownMenuItem>Hôm nay</DropdownMenuItem>
          <DropdownMenuItem>7 ngày gần nhất</DropdownMenuItem>
          <DropdownMenuItem>30 ngày gần nhất</DropdownMenuItem>
          <DropdownMenuItem>Quý gần nhất</DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </div>
  );
}
