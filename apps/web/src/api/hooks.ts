import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { api, type ChaosIn, type RuleIn, unwrap } from './client';

const keys = {
  workspaces: ['workspaces'] as const,
  workspace: (slug: string) => ['workspaces', slug] as const,
  routes: (slug: string) => ['workspaces', slug, 'routes'] as const,
  route: (slug: string, key: string) => ['workspaces', slug, 'routes', key] as const,
  sample: (slug: string, key: string, status: string) => ['workspaces', slug, 'routes', key, 'sample', status] as const,
  rules: (slug: string) => ['workspaces', slug, 'rules'] as const,
  chaos: (slug: string) => ['workspaces', slug, 'chaos'] as const,
  spec: (slug: string) => ['workspaces', slug, 'spec'] as const,
  versions: (slug: string) => ['workspaces', slug, 'versions'] as const,
};

export function useWorkspaces() {
  return useQuery({ queryKey: keys.workspaces, queryFn: () => unwrap(api.GET('/api/workspaces')) });
}

export function useWorkspace(slug: string) {
  return useQuery({
    queryKey: keys.workspace(slug),
    queryFn: () => unwrap(api.GET('/api/workspaces/{slug}', { params: { path: { slug } } })),
    retry: false,
  });
}

export function useCreateWorkspace() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name: string; slug?: string; spec_text?: string | null; rules?: RuleIn[] }) =>
      unwrap(api.POST('/api/workspaces', { body })),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.workspaces }),
  });
}

export function useDeleteWorkspace() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (slug: string) => unwrap(api.DELETE('/api/workspaces/{slug}', { params: { path: { slug } } })),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.workspaces }),
  });
}

export function useUpdateWorkspace(slug: string) {
  const client = useQueryClient();
  return useMutation({
    mutationFn: (body: { name?: string; seed?: number; validation_mode?: 'strict' | 'off' }) =>
      unwrap(api.PATCH('/api/workspaces/{slug}', { params: { path: { slug } }, body })),
    onSuccess: () => client.invalidateQueries({ queryKey: keys.workspace(slug) }),
  });
}

export function useRoutes(slug: string) {
  return useQuery({
    queryKey: keys.routes(slug),
    queryFn: () => unwrap(api.GET('/api/workspaces/{slug}/routes', { params: { path: { slug } } })),
  });
}

export function useRouteDetail(slug: string, key: string | null) {
  return useQuery({
    queryKey: keys.route(slug, key ?? ''),
    enabled: key !== null,
    queryFn: () =>
      unwrap(
        api.GET('/api/workspaces/{slug}/routes/detail', { params: { path: { slug }, query: { key: key ?? '' } } }),
      ),
  });
}

export function useResponseSample(slug: string, key: string, status: string) {
  return useQuery({
    queryKey: keys.sample(slug, key, status),
    queryFn: () =>
      unwrap(
        api.GET('/api/workspaces/{slug}/routes/sample', { params: { path: { slug }, query: { key, status } } }),
      ),
  });
}

export function useRules(slug: string) {
  return useQuery({
    queryKey: keys.rules(slug),
    queryFn: () => unwrap(api.GET('/api/workspaces/{slug}/rules', { params: { path: { slug } } })),
  });
}

function useInvalidateWorkspace(slug: string) {
  const client = useQueryClient();
  return () => client.invalidateQueries({ queryKey: keys.workspace(slug) });
}

export function useSaveRule(slug: string) {
  const invalidate = useInvalidateWorkspace(slug);
  return useMutation({
    mutationFn: ({ id, rule }: { id?: string; rule: RuleIn }) =>
      id
        ? unwrap(api.PUT('/api/workspaces/{slug}/rules/{rule_id}', { params: { path: { slug, rule_id: id } }, body: rule }))
        : unwrap(api.POST('/api/workspaces/{slug}/rules', { params: { path: { slug } }, body: rule })),
    onSuccess: invalidate,
  });
}

export function useDeleteRule(slug: string) {
  const invalidate = useInvalidateWorkspace(slug);
  return useMutation({
    mutationFn: (id: string) =>
      unwrap(api.DELETE('/api/workspaces/{slug}/rules/{rule_id}', { params: { path: { slug, rule_id: id } } })),
    onSuccess: invalidate,
  });
}

export function useChaos(slug: string) {
  return useQuery({
    queryKey: keys.chaos(slug),
    queryFn: () => unwrap(api.GET('/api/workspaces/{slug}/chaos', { params: { path: { slug } } })),
  });
}

export function useSetChaos(slug: string) {
  const invalidate = useInvalidateWorkspace(slug);
  return useMutation({
    mutationFn: (body: ChaosIn) => unwrap(api.PUT('/api/workspaces/{slug}/chaos', { params: { path: { slug } }, body })),
    onSuccess: invalidate,
  });
}

export function useClearChaos(slug: string) {
  const invalidate = useInvalidateWorkspace(slug);
  return useMutation({
    mutationFn: (routeKey: string | null) =>
      unwrap(
        api.DELETE('/api/workspaces/{slug}/chaos', {
          params: { path: { slug }, query: routeKey ? { route_key: routeKey } : {} },
        }),
      ),
    onSuccess: invalidate,
  });
}

export function useSpec(slug: string) {
  return useQuery({
    queryKey: keys.spec(slug),
    queryFn: () => unwrap(api.GET('/api/workspaces/{slug}/spec', { params: { path: { slug } } })),
  });
}

export function useSaveSpec(slug: string) {
  const invalidate = useInvalidateWorkspace(slug);
  return useMutation({
    mutationFn: (text: string) =>
      unwrap(api.PUT('/api/workspaces/{slug}/spec', { params: { path: { slug } }, body: { text } })),
    onSuccess: invalidate,
  });
}

export function useSpecVersions(slug: string) {
  return useQuery({
    queryKey: keys.versions(slug),
    queryFn: () => unwrap(api.GET('/api/workspaces/{slug}/spec/versions', { params: { path: { slug } } })),
  });
}

export function validateSpec(text: string) {
  return unwrap(api.POST('/api/specs/validate', { body: { text } }));
}
