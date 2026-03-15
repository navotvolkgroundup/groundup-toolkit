/**
 * Response freshness metadata wrapper.
 *
 * Wraps API response data with provenance information so the dashboard
 * can show stale-data indicators and the GP knows how fresh the data is.
 */

export interface FreshnessMeta {
  fetchedAt: string          // ISO timestamp of this response
  dataAge: number            // seconds since source data was last updated
  source: string             // 'hubspot' | 'sqlite' | 'gmail' | 'log_file' | 'cache'
  stale: boolean             // true if dataAge > staleThreshold
  cacheHit: boolean          // true if served from in-memory cache
}

export interface FreshnessEnvelope<T> {
  data: T
  meta: FreshnessMeta
}

/**
 * Wrap API response data with freshness metadata.
 *
 * @param data - The actual response payload
 * @param sourceTimestamp - When the source data was last updated (ISO string or ms epoch)
 * @param source - Where the data came from
 * @param staleThresholdSeconds - After how many seconds data is considered stale (default: 1 hour)
 * @param cacheHit - Whether this was served from cache
 */
export function withFreshness<T>(
  data: T,
  sourceTimestamp: string | number | null,
  source: string,
  staleThresholdSeconds = 3600,
  cacheHit = false,
): FreshnessEnvelope<T> {
  const now = new Date()
  let dataAge = 0

  if (sourceTimestamp) {
    const sourceDate = typeof sourceTimestamp === "number"
      ? new Date(sourceTimestamp)
      : new Date(sourceTimestamp)
    dataAge = Math.max(0, Math.floor((now.getTime() - sourceDate.getTime()) / 1000))
  }

  return {
    data,
    meta: {
      fetchedAt: now.toISOString(),
      dataAge,
      source,
      stale: dataAge > staleThresholdSeconds,
      cacheHit,
    },
  }
}
