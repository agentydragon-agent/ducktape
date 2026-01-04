import { fetchDefinitionDetail } from '$lib/api/client';

export async function load({ params }: { params: { definitionId: string } }) {
  const data = await fetchDefinitionDetail(params.definitionId);
  return { definition: data };
}
