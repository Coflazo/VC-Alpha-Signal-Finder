import type { ProductHuntLaunchRecord } from '../../lib/types';
import { makeId } from '../../lib/utils';

export async function searchProductHuntLaunches(query: string, token = ''): Promise<ProductHuntLaunchRecord[]> {
  if (!query.trim() || !token) return [];
  const graphQuery = `
    query SearchPosts($query: String!) {
      posts(search: $query, first: 10) {
        edges {
          node {
            name
            tagline
            url
            votesCount
            commentsCount
            featuredAt
            makers { name username }
          }
        }
      }
    }
  `;
  const response = await fetch('https://api.producthunt.com/v2/api/graphql', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify({ query: graphQuery, variables: { query } }),
  });
  if (!response.ok) return [];
  const json = await response.json();
  const edges = json?.data?.posts?.edges;
  if (!Array.isArray(edges)) return [];
  return edges.map((edge) => {
    const node = edge.node;
    return {
      id: makeId('ph_launch'),
      name: node.name ?? 'Unknown launch',
      url: node.url ?? '',
      tagline: node.tagline ?? '',
      makerNames: Array.isArray(node.makers) ? node.makers.map((maker: { name?: string; username?: string }) => maker.name || maker.username || 'unknown') : [],
      launchDate: node.featuredAt ?? '',
      votes: node.votesCount ?? 0,
      comments: node.commentsCount ?? 0,
      relatedPersonIds: [],
      evidenceIds: [],
    } satisfies ProductHuntLaunchRecord;
  });
}
