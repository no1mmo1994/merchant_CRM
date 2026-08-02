import { PageHeader } from "@/components/layout/page-header";
import { StoreDetailClient } from "./store-detail-client";

interface PageProps {
  params: Promise<{ merchantId: string }>;
}

export default async function StoreDetailPage({ params }: PageProps) {
  const { merchantId } = await params;
  return (
    <div className="space-y-6 p-6">
      <PageHeader
        title="Store details"
        description="Business attributes and live scorecard from Grab."
      />
      <StoreDetailClient merchantId={merchantId} />
    </div>
  );
}
