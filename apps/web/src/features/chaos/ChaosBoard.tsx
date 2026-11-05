import { Flame } from 'lucide-react';
import { useEffect, useState } from 'react';
import type { ChaosIn } from '@/api/client';
import { useChaos, useClearChaos, useRoutes, useSetChaos } from '@/api/hooks';
import { MethodBadge } from '@/components/MethodBadge';
import { Button } from '@/components/ui/button';
import { Label, Select } from '@/components/ui/fields';
import { Slider } from '@/components/ui/slider';
import { Switch } from '@/components/ui/switch';
import { useUi } from '@/store/ui';

const MAX_LATENCY = 10_000;
const FORCED = [200, 204, 400, 401, 403, 404, 409, 418, 422, 429, 500, 502, 503, 504];

type Settings = Required<Pick<ChaosIn, 'latency_min_ms' | 'latency_max_ms' | 'error_rate' | 'offline'>> & {
  forced_status: number | null;
};

const CALM: Settings = { latency_min_ms: 0, latency_max_ms: 0, error_rate: 0, forced_status: null, offline: false };

function seconds(ms: number): string {
  return ms === 0 ? '0' : ms < 1000 ? `${ms} ms` : `${(ms / 1000).toFixed(1)} s`;
}

function Controls({ value, onCommit, scope }: { value: Settings; onCommit: (settings: Settings) => void; scope: string }) {
  // Sliders track locally while dragging, and only save on release.
  const [local, setLocal] = useState(value);
  useEffect(() => setLocal(value), [value]);
  const ranged = local.latency_max_ms > 0 && local.latency_max_ms !== local.latency_min_ms;
  const [random, setRandom] = useState(ranged);
  useEffect(() => setRandom(value.latency_max_ms > 0 && value.latency_max_ms !== value.latency_min_ms), [value]);

  const commit = (next: Settings) => {
    setLocal(next);
    onCommit(next);
  };
  const latencyDisplay = random
    ? `${seconds(local.latency_min_ms)} to ${seconds(local.latency_max_ms)}`
    : seconds(local.latency_min_ms);

  return (
    <div className="space-y-4" role="group" aria-label={`${scope} chaos settings`}>
      <div>
        <div className="mb-1 flex items-center justify-between">
          <Label className="mb-0">Latency</Label>
          <div className="flex items-center gap-2 text-xs">
            <span className="font-mono">{latencyDisplay}</span>
            <label className="flex items-center gap-1 text-muted">
              <Switch
                label={`${scope} random latency range`}
                checked={random}
                onCheckedChange={(on) => {
                  setRandom(on);
                  commit(
                    on
                      ? { ...local, latency_max_ms: Math.max(local.latency_min_ms, 1000) }
                      : { ...local, latency_max_ms: 0 },
                  );
                }}
              />
              Random range
            </label>
          </div>
        </div>
        <Slider
          label={`${scope} latency`}
          max={MAX_LATENCY}
          step={50}
          value={random ? [local.latency_min_ms, local.latency_max_ms] : [local.latency_min_ms]}
          onValueChange={([low, high]) =>
            setLocal({ ...local, latency_min_ms: low, latency_max_ms: random ? (high ?? low) : 0 })
          }
          onValueCommit={([low, high]) =>
            commit({ ...local, latency_min_ms: low, latency_max_ms: random ? (high ?? low) : 0 })
          }
        />
      </div>

      <div>
        <div className="mb-1 flex items-center justify-between">
          <Label className="mb-0">Error rate</Label>
          <span className="font-mono text-xs">{Math.round(local.error_rate * 100)}%</span>
        </div>
        <Slider
          label={`${scope} error rate`}
          max={100}
          step={1}
          value={[Math.round(local.error_rate * 100)]}
          onValueChange={([percent]) => setLocal({ ...local, error_rate: percent / 100 })}
          onValueCommit={([percent]) => commit({ ...local, error_rate: percent / 100 })}
        />
      </div>

      <div className="flex flex-wrap items-end gap-4">
        <div>
          <Label htmlFor={`${scope}-forced`}>Forced status</Label>
          <Select
            id={`${scope}-forced`}
            className="w-32 font-mono text-xs"
            value={local.forced_status ?? ''}
            onChange={(event) =>
              commit({ ...local, forced_status: event.target.value ? Number(event.target.value) : null })
            }
          >
            <option value="">Off</option>
            {FORCED.map((status) => (
              <option key={status} value={status}>
                {status}
              </option>
            ))}
          </Select>
        </div>
        <label className="flex h-8 items-center gap-2">
          <Switch
            label={`${scope} offline`}
            checked={local.offline}
            onCheckedChange={(offline) => commit({ ...local, offline })}
          />
          <span>
            Offline <span className="text-xs text-muted">(drops the connection)</span>
          </span>
        </label>
      </div>
    </div>
  );
}

function pick(row: ChaosIn | undefined): Settings {
  if (!row) return CALM;
  return {
    latency_min_ms: row.latency_min_ms ?? 0,
    latency_max_ms: row.latency_max_ms ?? 0,
    error_rate: row.error_rate ?? 0,
    forced_status: row.forced_status ?? null,
    offline: row.offline ?? false,
  };
}

function isCalm(settings: Settings): boolean {
  return (
    !settings.latency_min_ms && !settings.latency_max_ms && !settings.error_rate && settings.forced_status === null && !settings.offline
  );
}

export function RouteChaos({ slug, routeKey }: { slug: string; routeKey: string }) {
  const chaos = useChaos(slug);
  const set = useSetChaos(slug);
  const clear = useClearChaos(slug);
  const toast = useUi((state) => state.toast);
  const row = chaos.data?.find((item) => item.route_key === routeKey);
  const global = chaos.data?.find((item) => item.route_key === null || item.route_key === undefined);
  const onError = (error: Error) => toast(error.message, 'bad');

  return (
    <div className="space-y-3 p-3">
      <label className="flex items-start gap-2">
        <Switch
          label="Use settings just for this route"
          checked={Boolean(row)}
          onCheckedChange={(on) =>
            on
              ? set.mutate({ route_key: routeKey, ...pick(global) }, { onError })
              : clear.mutate(routeKey, { onError })
          }
        />
        <span>
          Use settings just for this route
          <span className="block text-xs text-muted">
            {row
              ? 'These replace the global settings for this route.'
              : global && !isCalm(pick(global))
                ? 'Global chaos settings currently apply to this route.'
                : 'No chaos applies to this route at the moment.'}
          </span>
        </span>
      </label>
      {row && (
        <Controls scope="Route" value={pick(row)} onCommit={(next) => set.mutate({ route_key: routeKey, ...next }, { onError })} />
      )}
    </div>
  );
}

export function ChaosBoard({ slug }: { slug: string }) {
  const chaos = useChaos(slug);
  const routes = useRoutes(slug);
  const set = useSetChaos(slug);
  const clear = useClearChaos(slug);
  const toast = useUi((state) => state.toast);
  const onError = (error: Error) => toast(error.message, 'bad');
  const global = chaos.data?.find((item) => item.route_key === null || item.route_key === undefined);
  const overrides = chaos.data?.filter((item) => item.route_key) ?? [];

  return (
    <div className="h-full overflow-y-auto p-3">
      <h2 className="flex items-center gap-1.5 text-sm font-semibold">
        <Flame size={14} className="text-accent" /> Chaos board
      </h2>
      <p className="mt-0.5 text-xs text-muted">Simulate slow and flaky networks. Changes apply to the next request.</p>

      <section className="mt-3 rounded-lg border border-line bg-surface p-3" aria-label="Global chaos">
        <div className="mb-3 flex items-center justify-between">
          <h3 className="font-medium">All routes</h3>
          <Button
            size="sm"
            variant="ghost"
            disabled={!global || isCalm(pick(global))}
            onClick={() => clear.mutate(null, { onError })}
          >
            Reset
          </Button>
        </div>
        <Controls scope="Global" value={pick(global)} onCommit={(next) => set.mutate({ route_key: null, ...next }, { onError })} />
      </section>

      <section className="mt-4" aria-label="Route overrides">
        <h3 className="mb-1 font-medium">Routes with their own settings</h3>
        {overrides.length === 0 && (
          <p className="text-xs text-muted">None. Pick a route and open its Chaos tab to give it its own settings.</p>
        )}
        <div className="space-y-2">
          {overrides.map((row) => {
            const key = row.route_key!;
            const route = routes.data?.find((item) => item.key === key);
            return (
              <div key={key} className="rounded-lg border border-line bg-surface p-3">
                <div className="mb-3 flex items-center gap-1">
                  <MethodBadge method={route?.method ?? key.split(' ')[0]} />
                  <span className="min-w-0 flex-1 truncate font-mono text-xs">{route?.path ?? key.split(' ')[1]}</span>
                  <Button size="sm" variant="ghost" onClick={() => clear.mutate(key, { onError })}>
                    Remove
                  </Button>
                </div>
                <Controls scope={key} value={pick(row)} onCommit={(next) => set.mutate({ route_key: key, ...next }, { onError })} />
              </div>
            );
          })}
        </div>
      </section>
    </div>
  );
}
