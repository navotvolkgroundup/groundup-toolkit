import { NextRequest, NextResponse } from 'next/server'
import { auth } from '@/lib/auth'
import { rateLimit } from '@/lib/rate-limit'
import { withFreshness } from '@/lib/withFreshness'

const limiter = rateLimit({ interval: 60_000, limit: 20 })

export async function GET(request: NextRequest) {
  const { ok } = await limiter.check(request)
  if (!ok) return NextResponse.json({ error: 'Too Many Requests' }, { status: 429 })

  const session = await auth()
  if (!session) return NextResponse.json({ error: 'Unauthorized' }, { status: 401 })

  const { searchParams } = new URL(request.url)
  const companyName = searchParams.get('company')
  const domain = searchParams.get('domain')

  if (!companyName) {
    return NextResponse.json({ error: 'Missing company' }, { status: 400 })
  }

  try {
    const query = domain || companyName
    const googleNewsUrl = `https://news.google.com/rss/search?q=${encodeURIComponent(query)}&hl=en-US&gl=US&ceid=US:en`

    const rssRes = await fetch(googleNewsUrl, { next: { revalidate: 3600 } })
    const rssText = await rssRes.text()

    const items: { title: string; link: string; pubDate: string; source: string }[] = []
    const itemMatches = rssText.match(/<item>([\s\S]*?)<\/item>/g) || []

    for (const itemXml of itemMatches.slice(0, 3)) {
      const title = itemXml.match(/<title>(.*?)<\/title>/)?.[1]?.replace(/<!\[CDATA\[(.*?)\]\]>/, '$1') || ''
      const link = itemXml.match(/<link\/>\s*(.*?)(?=<)/)?.[1] || itemXml.match(/<link>(.*?)<\/link>/)?.[1] || ''
      const pubDate = itemXml.match(/<pubDate>(.*?)<\/pubDate>/)?.[1] || ''
      const source = itemXml.match(/<source.*?>(.*?)<\/source>/)?.[1] || ''
      if (title) items.push({ title, link: link.trim(), pubDate, source })
    }

    return NextResponse.json(withFreshness({ news: items }, null, "hubspot"))
  } catch (err: any) {
    return NextResponse.json({ news: [], error: err.message })
  }
}
