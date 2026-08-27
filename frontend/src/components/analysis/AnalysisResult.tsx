'use client'

import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Badge } from '@/components/ui/badge'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { TrendingUp, TrendingDown, AlertTriangle, CheckCircle2, DollarSign } from 'lucide-react'

interface AnalysisResultProps {
  result: any
}

export function AnalysisResult({ result }: AnalysisResultProps) {
  if (!result) return null

  const { technical_analysis, fundamental_analysis, sentiment_analysis, risk_assessment, decision, report, market_data, research_synthesis } = result

  // Get the first symbol
  const symbols = result?.symbols || []
  const firstSymbol = symbols[0] || Object.keys(fundamental_analysis || {})[0] || Object.keys(market_data || {})[0]

  // Confidence arrives as a 0-1 fraction since the decision-formula
  // unification; tolerate legacy 0-100 payloads.
  const confidencePct = (value: number | undefined): number | undefined =>
    value === undefined || value === null ? undefined : value <= 1 ? value * 100 : value

  const getSentimentIcon = (sentiment?: string) => {
    if (!sentiment) return null
    const s = sentiment.toLowerCase()
    if (s.includes('bullish') || s.includes('positive') || s.includes('buy')) {
      return <TrendingUp className="h-4 w-4 text-green-500" />
    }
    if (s.includes('bearish') || s.includes('negative') || s.includes('sell')) {
      return <TrendingDown className="h-4 w-4 text-red-500" />
    }
    return <AlertTriangle className="h-4 w-4 text-yellow-500" />
  }

  const getRiskBadge = (level?: string) => {
    if (!level) return <Badge variant="outline">Unknown</Badge>
    const l = String(level).toLowerCase()
    if (l.includes('low') || l.includes('very_low')) return <Badge variant="success">Low Risk</Badge>
    if (l.includes('high') || l.includes('very_high')) return <Badge variant="destructive">High Risk</Badge>
    return <Badge variant="warning">Moderate Risk</Badge>
  }

  // Get the first symbol's decision
  const decisions = decision?.decisions || {}
  const firstDecision = firstSymbol ? decisions[firstSymbol] : null

  // Get fundamental data for first symbol
  const fundamentalBySymbol = fundamental_analysis && typeof fundamental_analysis === 'object' ? fundamental_analysis : {}
  const firstFundamental = firstSymbol ? fundamentalBySymbol[firstSymbol] : null

  // V2 research fields (raw pipeline state shape)
  const weekly = firstSymbol ? technical_analysis?.[firstSymbol]?.weekly_sma : null
  const quality = firstFundamental?.quality
  const valuationScenarios = firstFundamental?.valuation_scenarios
  const synthesisEntry = research_synthesis?.per_symbol?.[firstSymbol]

  // Get risk data for first symbol
  const riskBySymbol = risk_assessment?.risk_by_symbol || {}
  const firstSymbolRisk = firstSymbol ? riskBySymbol[firstSymbol] : null
  const overallRiskLevel = risk_assessment?.overall_risk_level || firstSymbolRisk?.risk_level

  // Get market data for first symbol
  const marketBySymbol = market_data || {}
  const firstMarket = firstSymbol ? marketBySymbol[firstSymbol] : null

  return (
    <div className="space-y-4">
      {/* Summary Card */}
      <Card className="bg-primary/5 border-primary/20">
        <CardHeader>
          <CardTitle className="flex items-center gap-2">
            <CheckCircle2 className="h-5 w-5 text-green-500" />
            Analysis Complete
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-2">
          {firstMarket && (
            <div className="flex items-center justify-between">
              <div>
                <h3 className="text-lg font-semibold">{firstMarket.company_name || firstSymbol}</h3>
                <p className="text-sm text-muted-foreground">{firstSymbol} • {firstMarket.sector || 'Technology'}</p>
              </div>
              <div className="text-right">
                <p className="text-2xl font-bold">${firstMarket.current_price?.toFixed(2)}</p>
                <p className={firstMarket.change && firstMarket.change >= 0 ? 'text-sm text-green-600' : 'text-sm text-red-600'}>
                  {firstMarket.change && firstMarket.change >= 0 ? '+' : ''}{firstMarket.change?.toFixed(2)} ({firstMarket.change_percent?.toFixed(2)}%)
                </p>
              </div>
            </div>
          )}
          {report?.executive_summary && (
            <p className="text-sm text-muted-foreground mt-2 pt-2 border-t">{report.executive_summary}</p>
          )}
        </CardContent>
      </Card>

      <Tabs defaultValue="technical" className="w-full">
        <TabsList className="grid w-full grid-cols-4">
          <TabsTrigger value="technical">Technical</TabsTrigger>
          <TabsTrigger value="fundamental">Fundamental</TabsTrigger>
          <TabsTrigger value="sentiment">Sentiment</TabsTrigger>
          <TabsTrigger value="risk">Risk & Decision</TabsTrigger>
        </TabsList>

        <TabsContent value="technical" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Technical Analysis</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {firstSymbol && technical_analysis && technical_analysis[firstSymbol] ? (
                <>
                  {technical_analysis[firstSymbol]?.indicators && (
                    <div>
                      <h4 className="font-semibold mb-2">Key Indicators</h4>
                      <div className="grid grid-cols-2 gap-4">
                        {Object.entries(technical_analysis[firstSymbol].indicators).slice(0, 8).map(([key, value]: [string, any]) => (
                          <div key={key} className="flex justify-between text-sm">
                            <span className="text-muted-foreground capitalize">{key.replace(/_/g, ' ')}</span>
                            <span className="font-medium">{typeof value === 'number' ? value.toFixed(2) : String(value)}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {technical_analysis[firstSymbol]?.signals && typeof technical_analysis[firstSymbol].signals === 'object' && Object.keys(technical_analysis[firstSymbol].signals).length > 0 ? (
                    <div>
                      <h4 className="font-semibold mb-2">Trading Signals</h4>
                      <div className="flex flex-wrap gap-2">
                        {Object.entries(technical_analysis[firstSymbol].signals).map(([key, value]: [string, any]) => (
                          <Badge key={key} variant="outline">{String(value)}</Badge>
                        ))}
                      </div>
                    </div>
                  ) : null}
                  {technical_analysis[firstSymbol]?.sentiment && (
                    <div>
                      <h4 className="font-semibold mb-2">Technical Sentiment</h4>
                      <div className="flex items-center gap-2">
                        {getSentimentIcon(technical_analysis[firstSymbol].sentiment.sentiment)}
                        <span className="text-sm">{String(technical_analysis[firstSymbol].sentiment.sentiment || 'neutral').toUpperCase()}</span>
                        <Badge variant={technical_analysis[firstSymbol].sentiment.score > 0 ? 'success' : 'secondary'}>
                          Score: {technical_analysis[firstSymbol].sentiment.score}
                        </Badge>
                      </div>
                    </div>
                  )}
                  {weekly && weekly.status === 'available' && weekly.alignment && (
                    <div>
                      <h4 className="font-semibold mb-2">Weekly Trend (5/10/20/40/60w SMA)</h4>
                      <div className="flex items-center gap-2 mb-2">
                        <Badge variant={weekly.alignment.state === 'bullish' ? 'success' : weekly.alignment.state === 'bearish' ? 'destructive' : 'secondary'}>
                          {weekly.alignment.state === 'bullish' ? 'Bullish alignment' : weekly.alignment.state === 'bearish' ? 'Bearish alignment' : 'Mixed / tangled'}
                        </Badge>
                        {weekly.alignment.weeks_in_state != null && (
                          <span className="text-xs text-muted-foreground">for {weekly.alignment.weeks_in_state} weeks</span>
                        )}
                      </div>
                      {Object.entries(weekly.crosses || {}).map(([pair, cross]: [string, any]) =>
                        cross?.status === 'observed' && (cross.weeks_since ?? 99) <= 13 ? (
                          <div key={pair} className="flex justify-between text-sm">
                            <span className="text-muted-foreground">Cross {pair.replace('_vs_', '/')}</span>
                            <span className={cross.direction === 'golden' ? 'text-green-600 font-medium' : 'text-red-600 font-medium'}>
                              {cross.direction === 'golden' ? 'Golden' : 'Death'} · {cross.weeks_since}w ago
                            </span>
                          </div>
                        ) : null
                      )}
                    </div>
                  )}
                  {weekly && weekly.status === 'insufficient_data' && (
                    <p className="text-sm text-muted-foreground">Weekly trend: insufficient data (needs ~3y history).</p>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">No technical analysis data available.</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="fundamental" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle>Fundamental Analysis</CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {firstFundamental ? (
                <>
                  <div className="flex items-center justify-between p-3 bg-muted rounded-lg">
                    <span className="text-sm font-medium">Overall Score</span>
                    <Badge variant={firstFundamental.overall_score?.rating === 'good' || firstFundamental.overall_score?.rating === 'fair' ? 'success' : 'destructive'}>
                      {firstFundamental.overall_score?.score || 0}/100 - {String(firstFundamental.overall_score?.rating || 'N/A').toUpperCase()}
                    </Badge>
                  </div>
                  {firstFundamental.recommendation && (
                    <div className="flex items-center justify-between p-3 bg-muted rounded-lg">
                      <span className="text-sm font-medium">Recommendation</span>
                      <Badge variant={firstFundamental.recommendation.toLowerCase().includes('buy') ? 'success' : firstFundamental.recommendation.toLowerCase().includes('sell') ? 'destructive' : 'secondary'}>
                        {String(firstFundamental.recommendation).replace('_', ' ').toUpperCase()}
                      </Badge>
                    </div>
                  )}
                  {firstFundamental.profitability && (
                    <div>
                      <h4 className="font-semibold mb-2">Profitability</h4>
                      <div className="space-y-2">
                        <div className="flex justify-between text-sm">
                          <span className="text-muted-foreground">ROE</span>
                          <span className="font-medium">{(firstFundamental.profitability.details?.roe || 0).toFixed(2)}</span>
                        </div>
                        <div className="flex justify-between text-sm">
                          <span className="text-muted-foreground">ROA</span>
                          <span className="font-medium">{(firstFundamental.profitability.details?.roa || 0).toFixed(2)}</span>
                        </div>
                        <div className="flex justify-between text-sm">
                          <span className="text-muted-foreground">Profit Margin</span>
                          <span className="font-medium">{((firstFundamental.profitability.details?.profit_margin || 0) * 100).toFixed(2)}%</span>
                        </div>
                      </div>
                    </div>
                  )}
                  {firstFundamental.valuation && (
                    <div>
                      <h4 className="font-semibold mb-2">Valuation</h4>
                      <div className="space-y-2">
                        <div className="flex justify-between text-sm">
                          <span className="text-muted-foreground">P/E Ratio</span>
                          <span className="font-medium">{(firstFundamental.valuation.details?.pe_ratio || 0).toFixed(2)}</span>
                        </div>
                        <div className="flex justify-between text-sm">
                          <span className="text-muted-foreground">P/B Ratio</span>
                          <span className="font-medium">{(firstFundamental.valuation.details?.pb_ratio || 0).toFixed(2)}</span>
                        </div>
                      </div>
                    </div>
                  )}
                  {valuationScenarios?.status === 'available' && valuationScenarios.methods && (
                    <div>
                      <h4 className="font-semibold mb-2">Valuation Scenarios (range, not a target price)</h4>
                      <div className="grid grid-cols-3 gap-2">
                        {(['bear', 'base', 'bull'] as const).map(scenario => {
                          const values = Object.values(valuationScenarios.methods)
                            .map((method: any) => method?.scenarios?.[scenario])
                            .filter(Boolean)
                          const first = values[0]
                          const upside = values.length ? Math.max(...values.map((v: any) => v.upside_pct ?? -Infinity)) : undefined
                          return (
                            <div key={scenario} className="p-2 border rounded text-center">
                              <p className="text-xs text-muted-foreground capitalize">{scenario}</p>
                              <p className={`text-sm font-semibold ${scenario === 'bear' ? 'text-red-600' : scenario === 'bull' ? 'text-green-600' : ''}`}>
                                {first?.value != null ? `$${first.value.toFixed(2)}` : 'N/A'}
                              </p>
                              {upside !== undefined && Number.isFinite(upside) && (
                                <p className={`text-xs ${upside >= 0 ? 'text-green-600' : 'text-red-600'}`}>
                                  {upside >= 0 ? '+' : ''}{upside.toFixed(1)}%
                                </p>
                              )}
                            </div>
                          )
                        })}
                      </div>
                    </div>
                  )}
                  {quality?.red_flags?.length > 0 && (
                    <div>
                      <h4 className="font-semibold mb-2">Quality Red Flags</h4>
                      <ul className="space-y-1">
                        {quality.red_flags.map((flag: any, i: number) => (
                          <li key={i} className="text-sm flex items-start gap-2">
                            <AlertTriangle className={`h-4 w-4 mt-0.5 flex-shrink-0 ${flag.severity === 'critical' ? 'text-red-500' : 'text-yellow-500'}`} />
                            <span className={flag.severity === 'critical' ? 'text-red-600 font-medium' : ''}>
                              {flag.detail || flag.code}
                            </span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">No fundamental analysis data available.</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="sentiment" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Sentiment Analysis
                {getSentimentIcon(sentiment_analysis?.overall?.sentiment || sentiment_analysis?.overall_sentiment)}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {sentiment_analysis && Object.keys(sentiment_analysis).length > 0 ? (
                <>
                  {(sentiment_analysis?.overall?.sentiment || sentiment_analysis?.overall_sentiment) && (
                    <div>
                      <h4 className="font-semibold mb-2">Overall Sentiment</h4>
                      <Badge variant={(sentiment_analysis.overall?.sentiment || sentiment_analysis.overall_sentiment)?.toLowerCase().includes('bullish') ? 'success' : 'secondary'}>
                        {sentiment_analysis.overall?.sentiment || sentiment_analysis.overall_sentiment}
                      </Badge>
                    </div>
                  )}
                  {sentiment_analysis?.overall?.trend && (
                    <div>
                      <h4 className="font-semibold mb-2">Trend</h4>
                      <p className="text-sm text-muted-foreground">{sentiment_analysis.overall.trend}</p>
                    </div>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">No sentiment analysis data available.</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>

        <TabsContent value="risk" className="space-y-4">
          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                Risk Assessment
                {getRiskBadge(overallRiskLevel)}
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {firstMarket && (
                <div>
                  <h4 className="font-semibold mb-2">Market Data</h4>
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <p className="text-xs text-muted-foreground">Current Price</p>
                      <p className="text-lg font-medium">${firstMarket.current_price?.toFixed(2) || 'N/A'}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Change</p>
                      <p className={firstMarket.change && firstMarket.change >= 0 ? 'text-lg font-medium text-green-600' : 'text-lg font-medium text-red-600'}>
                        {firstMarket.change && firstMarket.change >= 0 ? '+' : ''}{firstMarket.change?.toFixed(2) || 'N/A'} ({firstMarket.change_percent?.toFixed(2) || 0}%)
                      </p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Volume</p>
                      <p className="text-sm font-medium">{(firstMarket.volume || 0).toLocaleString()}</p>
                    </div>
                    <div>
                      <p className="text-xs text-muted-foreground">Market Cap</p>
                      <p className="text-sm font-medium">${((firstMarket.market_cap || 0) / 1e12).toFixed(2)}T</p>
                    </div>
                  </div>
                </div>
              )}
              {firstSymbolRisk ? (
                <>
                  <div>
                    <h4 className="font-semibold mb-2">Risk Metrics</h4>
                    <div className="space-y-2">
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">Risk Score</span>
                        <span className="font-medium">{firstSymbolRisk.risk_score}/100</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">Volatility (Annual)</span>
                        <span className="font-medium">{(firstSymbolRisk.metrics?.volatility_annualized * 100).toFixed(2)}%</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">Max Drawdown</span>
                        <span className="font-medium">{(firstSymbolRisk.metrics?.max_drawdown * 100).toFixed(2)}%</span>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span className="text-muted-foreground">Beta</span>
                        <span className="font-medium">{firstSymbolRisk.metrics?.beta || 'N/A'}</span>
                      </div>
                    </div>
                  </div>
                  {firstSymbolRisk.position_recommendation && (
                    <div>
                      <h4 className="font-semibold mb-2">Position Recommendation</h4>
                      <div className="space-y-2">
                        <div className="flex justify-between text-sm">
                          <span className="text-muted-foreground">Max Position Size</span>
                          <span className="font-medium">{firstSymbolRisk.position_recommendation.max_position_size}%</span>
                        </div>
                        <div className="flex justify-between text-sm">
                          <span className="text-muted-foreground">Stop Loss</span>
                          <span className="font-medium text-destructive">{firstSymbolRisk.position_recommendation.stop_loss_percentage?.toFixed(2)}%</span>
                        </div>
                      </div>
                    </div>
                  )}
                  {firstSymbolRisk.warnings && firstSymbolRisk.warnings.length > 0 && (
                    <div>
                      <h4 className="font-semibold mb-2">Warnings</h4>
                      <ul className="space-y-1">
                        {firstSymbolRisk.warnings.map((factor: string, i: number) => (
                          <li key={i} className="text-sm flex items-start gap-2">
                            <AlertTriangle className="h-4 w-4 text-yellow-500 mt-0.5 flex-shrink-0" />
                            <span>{factor}</span>
                          </li>
                        ))}
                      </ul>
                    </div>
                  )}
                </>
              ) : (
                <p className="text-sm text-muted-foreground">No risk assessment data available.</p>
              )}
            </CardContent>
          </Card>

          <Card>
            <CardHeader>
              <CardTitle className="flex items-center gap-2">
                <DollarSign className="h-5 w-5" />
                Investment Recommendation
              </CardTitle>
            </CardHeader>
            <CardContent className="space-y-4">
              {synthesisEntry && (
                <div className="p-3 bg-muted rounded-lg space-y-2">
                  <div className="flex items-center justify-between">
                    <h4 className="font-semibold">Research Synthesis</h4>
                    <Badge
                      variant={
                        synthesisEntry.committee?.verdict === 'approve' ? 'success'
                          : synthesisEntry.committee?.verdict === 'veto' ? 'destructive'
                            : synthesisEntry.committee?.verdict === 'limit' ? 'warning' : 'secondary'
                      }
                    >
                      Committee: {String(synthesisEntry.committee?.verdict || 'watch').toUpperCase()}
                    </Badge>
                  </div>
                  {synthesisEntry.debate?.thesis && (
                    <p className="text-sm"><span className="text-green-600 font-medium">Bull thesis: </span>{synthesisEntry.debate.thesis}</p>
                  )}
                  {synthesisEntry.debate?.strongest_counter && (
                    <p className="text-sm"><span className="text-red-600 font-medium">Strongest counter: </span>{synthesisEntry.debate.strongest_counter}</p>
                  )}
                  {synthesisEntry.debate?.invalidation && (
                    <p className="text-xs text-muted-foreground">Thesis invalidation: {synthesisEntry.debate.invalidation}</p>
                  )}
                  {synthesisEntry.pm?.thesis && (
                    <p className="text-sm border-t pt-2"><span className="font-medium">PM: </span>{synthesisEntry.pm.thesis}
                      {synthesisEntry.pm.horizon ? <span className="text-xs text-muted-foreground"> (horizon: {synthesisEntry.pm.horizon})</span> : null}
                    </p>
                  )}
                  {synthesisEntry.committee?.conditions?.length > 0 && (
                    <ul className="text-xs text-muted-foreground list-disc pl-4 space-y-0.5">
                      {synthesisEntry.committee.conditions.map((condition: string, i: number) => <li key={i}>{condition}</li>)}
                    </ul>
                  )}
                  {synthesisEntry.committee?.position_cap_pct != null && (
                    <p className="text-xs text-muted-foreground">Position cap: {synthesisEntry.committee.position_cap_pct}%</p>
                  )}
                </div>
              )}
              {firstDecision ? (
                <>
                  <div>
                    <h4 className="font-semibold mb-2">Recommendation</h4>
                    <Badge
                      variant={
                        firstDecision.action?.toLowerCase().includes('buy')
                          ? 'success'
                          : firstDecision.action?.toLowerCase().includes('sell')
                          ? 'destructive'
                          : 'secondary'
                      }
                      className="text-base px-4 py-1"
                    >
                      {firstDecision.action || 'N/A'}
                    </Badge>
                  </div>
                  {firstDecision?.confidence !== undefined && (
                    <div>
                      <h4 className="font-semibold mb-2">Confidence Level</h4>
                      <div className="flex items-center gap-2">
                        <div className="w-full bg-muted rounded-full h-2">
                          <div
                            className="bg-primary h-2 rounded-full transition-all"
                            style={{ width: `${confidencePct(firstDecision.confidence) ?? 0}%` }}
                          />
                        </div>
                        <span className="text-sm font-medium">{(confidencePct(firstDecision.confidence) ?? 0).toFixed(0)}%</span>
                      </div>
                    </div>
                  )}
                  {firstDecision?.rationale && (
                    <div>
                      <h4 className="font-semibold mb-2">Rationale</h4>
                      <p className="text-sm text-muted-foreground">{firstDecision.rationale}</p>
                    </div>
                  )}
                  {firstDecision?.price_targets && (
                    <div>
                      <h4 className="font-semibold mb-2">Price Targets</h4>
                      <div className="space-y-1 text-sm">
                        {firstDecision.price_targets.entry_zone && (
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Entry Zone:</span>
                            <span className="font-medium">{firstDecision.price_targets.entry_zone}</span>
                          </div>
                        )}
                        {firstDecision.price_targets.stop_loss && (
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Stop Loss:</span>
                            <span className="font-medium text-destructive">{firstDecision.price_targets.stop_loss}</span>
                          </div>
                        )}
                        {firstDecision.price_targets.take_profit && (
                          <div className="flex justify-between">
                            <span className="text-muted-foreground">Take Profit:</span>
                            <span className="font-medium text-green-600">{firstDecision.price_targets.take_profit}</span>
                          </div>
                        )}
                      </div>
                    </div>
                  )}
                </>
              ) : firstFundamental ? (
                // Show fundamental recommendation as fallback
                <>
                  <div>
                    <h4 className="font-semibold mb-2">Fundamental Analysis Recommendation</h4>
                    <Badge
                      variant={
                        firstFundamental.recommendation?.toLowerCase().includes('buy')
                          ? 'success'
                          : firstFundamental.recommendation?.toLowerCase().includes('sell')
                          ? 'destructive'
                          : 'secondary'
                      }
                      className="text-base px-4 py-1"
                    >
                      {String(firstFundamental.recommendation || 'N/A').replace('_', ' ').toUpperCase()}
                    </Badge>
                  </div>
                  <div>
                    <h4 className="font-semibold mb-2">Overall Score</h4>
                    <div className="flex items-center gap-2">
                      <div className="w-full bg-muted rounded-full h-2">
                        <div
                          className={`h-2 rounded-full transition-all ${
                            firstFundamental.overall_score?.score >= 65 ? 'bg-green-600' :
                            firstFundamental.overall_score?.score >= 35 ? 'bg-yellow-600' : 'bg-red-600'
                          }`}
                          style={{ width: `${firstFundamental.overall_score?.score || 0}%` }}
                        />
                      </div>
                      <span className="text-sm font-medium">{firstFundamental.overall_score?.score || 0}/100</span>
                    </div>
                    <p className="text-xs text-muted-foreground mt-1">
                      Rating: {String(firstFundamental.overall_score?.rating || 'N/A').toUpperCase()}
                    </p>
                  </div>
                </>
              ) : (
                <p className="text-sm text-muted-foreground">No investment recommendation available.</p>
              )}
            </CardContent>
          </Card>
        </TabsContent>
      </Tabs>
    </div>
  )
}
