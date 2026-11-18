import SQLite3
import SwiftUI

/// Decision requests recorded by the gateway's analytics store, bucketed over a window.
struct UsageSnapshot: Sendable, Equatable {
    /// Request counts per bucket, oldest slot first.
    let buckets: [Int]
    /// Cache-hit counts per bucket (a subset of `buckets`): answers served by the
    /// gateway's replay cache instead of a live model call.
    let cachedBuckets: [Int]
    let total: Int
    let cached: Int
    /// Tokens the cache hits avoided (the original live calls' usage, stored per
    /// cache entry), the provider time they avoided, and the rate-card value of
    /// those avoided tokens.
    let savedInputTokens: Int
    let savedOutputTokens: Int
    let savedMs: Double
    let savedCost: Double
    let latestActivity: Date?
    /// Right edge of the window at snapshot time; hour markers align against it.
    let windowEnd: Date
}

/// Reads request timestamps straight from the analytics database the gateway already
/// maintains (one `requests` row per incoming `/v1/decision` call, including replay
/// cache hits). Opening read-only never contends with the recorder's writer lock or
/// changes its contents.
enum UsageHistory {
    static let window: TimeInterval = 12 * 3600
    static let bucketCount = 72
    static let bucketSeconds = window / TimeInterval(bucketCount)

    static var databaseURL: URL {
        FileManager.default.homeDirectoryForCurrentUser
            .appendingPathComponent("Library/Application Support/JEV Menu Bar/analytics/requests.sqlite3")
    }

    /// Synchronous, blocking read; run from a background task. `rates` prices the
    /// avoided tokens on cache-hit rows (keyed by model, dollars per million).
    static func snapshot(now: Date = Date(), rates: [String: ModelRate] = [:]) -> UsageSnapshot? {
        var database: OpaquePointer?
        guard sqlite3_open_v2(databaseURL.path, &database, SQLITE_OPEN_READONLY, nil) == SQLITE_OK,
              database != nil else {
            sqlite3_close_v2(database)
            return nil
        }
        defer { sqlite3_close_v2(database) }
        var statement: OpaquePointer?
        let query = "SELECT started_at, outcome, model, input_tokens, output_tokens, duration_ms FROM requests WHERE started_at >= ?"
        guard sqlite3_prepare_v2(database, query, -1, &statement, nil) == SQLITE_OK,
              statement != nil else {
            return nil
        }
        defer { sqlite3_finalize(statement) }
        sqlite3_bind_double(statement, 1, now.addingTimeInterval(-window).timeIntervalSince1970)
        var buckets = [Int](repeating: 0, count: bucketCount)
        var cachedBuckets = [Int](repeating: 0, count: bucketCount)
        var total = 0
        var cached = 0
        var savedInputTokens = 0
        var savedOutputTokens = 0
        var savedMs = 0.0
        var savedCost = 0.0
        var latestActivity: Date?
        let windowStart = now.addingTimeInterval(-window)
        while sqlite3_step(statement) == SQLITE_ROW {
            let started = Date(timeIntervalSince1970: sqlite3_column_double(statement, 0))
            let slot = Int(started.timeIntervalSince(windowStart) / bucketSeconds)
            let clamped = min(max(slot, 0), bucketCount - 1)
            buckets[clamped] += 1
            total += 1
            var isCacheHit = false
            if let column = sqlite3_column_text(statement, 1) {
                isCacheHit = String(cString: column) == "cache_hit"
            }
            if isCacheHit {
                cachedBuckets[clamped] += 1
                cached += 1
                let input = Int(sqlite3_column_int(statement, 3))
                let output = Int(sqlite3_column_int(statement, 4))
                let duration = sqlite3_column_double(statement, 5)
                savedInputTokens += input
                savedOutputTokens += output
                savedMs += duration
                var model: String?
                if let column = sqlite3_column_text(statement, 2) { model = String(cString: column) }
                if let rate = model.flatMap({ rates[$0] }) {
                    savedCost += (Double(input) * rate.inputPerMTok + Double(output) * rate.outputPerMTok) / 1_000_000
                }
            }
            latestActivity = started
        }
        return UsageSnapshot(buckets: buckets, cachedBuckets: cachedBuckets, total: total, cached: cached,
                             savedInputTokens: savedInputTokens, savedOutputTokens: savedOutputTokens,
                             savedMs: savedMs, savedCost: savedCost,
                             latestActivity: latestActivity, windowEnd: now)
    }
}

/// Pulse strip that replaces the divider under the health-check line: the divider's
/// line becomes the baseline, and every 10-minute bucket with requests draws a bar —
/// blue for live model calls with the cache-hit share stacked on top in green — so
/// quiet stretches read as a flatline and bursts read as blips.
struct UsagePulseView: View {
    let snapshot: UsageSnapshot?

    private let stripHeight: CGFloat = 34
    private let axisHeight: CGFloat = 14

    var body: some View {
        VStack(alignment: .leading, spacing: 4) {
            Canvas { context, size in
                let baselineY = size.height - axisHeight - 0.5
                var baseline = Path()
                baseline.move(to: CGPoint(x: 0, y: baselineY))
                baseline.addLine(to: CGPoint(x: size.width, y: baselineY))
                context.stroke(baseline, with: .color(Color(nsColor: .separatorColor)), lineWidth: 1)
                drawHourAxis(in: context, width: size.width, baselineY: baselineY)
                guard let snapshot else { return }
                let peak = zip(snapshot.buckets, snapshot.cachedBuckets).map { $0 + $1 }.max() ?? 0
                guard peak > 0 else { return }
                let slotWidth = size.width / CGFloat(snapshot.buckets.count)
                let barWidth = max(1, slotWidth - 1)
                let maxHeight = baselineY - 2
                for (index, value) in snapshot.buckets.enumerated() where value > 0 {
                    let cached = snapshot.cachedBuckets[index]
                    let liveHeight = max(2, maxHeight * CGFloat(value) / CGFloat(peak))
                    let x = CGFloat(index) * slotWidth
                    let liveRect = CGRect(x: x, y: baselineY - liveHeight, width: barWidth, height: liveHeight)
                    context.fill(Path(liveRect), with: .color(Color.accentColor.opacity(value + cached == peak ? 0.95 : 0.7)))
                    if cached > 0 {
                        // Cached answers stack on top of the live bar in green, on the same scale.
                        let cachedHeight = max(2, maxHeight * CGFloat(cached) / CGFloat(peak))
                        let cachedRect = CGRect(x: x, y: liveRect.minY - cachedHeight, width: barWidth, height: cachedHeight)
                        context.fill(Path(cachedRect), with: .color(.green.opacity(value + cached == peak ? 0.95 : 0.75)))
                    }
                }
            }
            .frame(height: stripHeight + axisHeight)
            HStack {
                Text("Last 12 hours").font(.caption2).foregroundStyle(.secondary)
                Spacer()
                Text(caption).font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
            }
            HStack {
                Text("Savings").font(.caption2).foregroundStyle(.secondary)
                Spacer()
                Text(savingsCaption).font(.caption2.monospacedDigit()).foregroundStyle(.secondary)
            }
        }
        .accessibilityElement(children: .ignore)
        .accessibilityLabel(accessibilityText)
    }

    /// Hour ruler under the baseline: a small tick at every whole clock hour in the
    /// window, plus a zero-padded 24-hour label (00, 04, 08, …) at every fourth hour.
    private func drawHourAxis(in context: GraphicsContext, width: CGFloat, baselineY: CGFloat) {
        guard let snapshot else { return }
        let calendar = Calendar.current
        let windowStart = snapshot.windowEnd.addingTimeInterval(-UsageHistory.window)
        guard var hour = calendar.nextDate(after: windowStart, matching: DateComponents(minute: 0, second: 0),
                                           matchingPolicy: .nextTime) else { return }
        let tickColor = Color(nsColor: .separatorColor)
        while hour <= snapshot.windowEnd {
            let fraction = hour.timeIntervalSince(windowStart) / UsageHistory.window
            let x = min(max(CGFloat(fraction) * width, 0.5), width - 0.5)
            var tick = Path()
            tick.move(to: CGPoint(x: x, y: baselineY + 1))
            tick.addLine(to: CGPoint(x: x, y: baselineY + 4))
            context.stroke(tick, with: .color(tickColor), lineWidth: 1)
            let value = calendar.component(.hour, from: hour)
            if value % 4 == 0 {
                let label = Text(String(format: "%02d", value))
                    .font(.system(size: 9).monospacedDigit())
                    .foregroundColor(.secondary)
                context.draw(label, at: CGPoint(x: min(max(x, 7), width - 7), y: baselineY + axisHeight / 2))
            }
            guard let next = calendar.date(byAdding: .hour, value: 1, to: hour) else { break }
            hour = next
        }
    }

    private var caption: String {
        guard let snapshot else { return "usage history unavailable" }
        // Request is the total for the window; Cache is how many of those
        // total requests the replay cache answered without a live model call.
        return "Request: \(snapshot.total)  ·  Cache: \(snapshot.cached)"
    }

    /// Cache-hit savings over the window: the provider spend the hits avoided
    /// (rate-card priced) and the model time they avoided, as H:MM:SS.
    private var savingsCaption: String {
        guard let snapshot else { return "" }
        let seconds = Int(snapshot.savedMs / 1000)
        let time = String(format: "%d:%02d:%02d", seconds / 3600, (seconds % 3600) / 60, seconds % 60)
        return "Cost: \(String(format: "$%.3f", snapshot.savedCost))  ·  Time: \(time)"
    }

    private var accessibilityText: String {
        guard let snapshot else { return "Usage history unavailable" }
        return "Usage in the last 12 hours: \(snapshot.total) requests, \(snapshot.cached) served from cache, "
            + String(format: "saving $%.3f and ", snapshot.savedCost)
            + "\(Int(snapshot.savedMs / 1000)) seconds of model time"
    }
}
