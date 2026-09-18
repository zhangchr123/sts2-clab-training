using System.Reflection;
using System.Security.Cryptography;
using System.Text.Json;
using MegaCrit.Sts2.Core.Entities.Cards;
using MegaCrit.Sts2.Core.Runs;
using Sts2Headless;

var sim = new RunSimulator();
var start = sim.StartRun("Defect", 10, "defect-reward-pool-probe-20260918", "en");
if (Equals(start.GetValueOrDefault("type"), "error"))
    throw new InvalidOperationException(JsonSerializer.Serialize(start));

var runField = typeof(RunSimulator).GetField("_runState", BindingFlags.Instance | BindingFlags.NonPublic)
    ?? throw new MissingFieldException("RunSimulator._runState");
var run = (RunState?)runField.GetValue(sim)
    ?? throw new InvalidOperationException("Run state was not initialized");
var runView = (IRunState)run;
var player = run.Players[0];
var previewMethod = typeof(RunSimulator).GetMethod(
    "WithUpgradePreview", BindingFlags.Instance | BindingFlags.NonPublic)
    ?? throw new MissingMethodException("RunSimulator.WithUpgradePreview");

var rows = new List<Dictionary<string, object?>>();
foreach (var canonical in player.Character.CardPool
             .GetUnlockedCards(player.UnlockState, runView.CardMultiplayerConstraint)
             .OrderBy(card => card.Id.Entry, StringComparer.Ordinal))
{
    var card = run.CreateCard(canonical, player);
    var stats = new Dictionary<string, object?>();
    foreach (var dynamicVar in card.DynamicVars.Values)
        stats[dynamicVar.Name.ToLowerInvariant()] = (int)dynamicVar.BaseValue;
    var keywords = card.Keywords?
        .Where(keyword => keyword != CardKeyword.None)
        .Select(keyword => keyword.ToString())
        .ToList();
    var exported = new Dictionary<string, object?>
    {
        ["id"] = card.Id.ToString(),
        ["cost"] = card.EnergyCost?.GetResolved() ?? 0,
        ["type"] = card.Type.ToString(),
        ["rarity"] = card.Rarity.ToString(),
        ["upgraded"] = card.IsUpgraded,
        ["stats"] = stats.Count == 0 ? null : stats,
        ["keywords"] = keywords?.Count > 0 ? keywords : null,
    };
    rows.Add((Dictionary<string, object?>)previewMethod.Invoke(sim, new object?[] { exported, card })!);
}

var enginePath = "C:/Users/zhangchr/Documents/code/sts2-cli/lib/sts2.dll";
var result = new Dictionary<string, object?>
{
    ["schema_version"] = "defect-current-public-reward-pool-v1",
    ["engine_sha256"] = Convert.ToHexString(SHA256.HashData(File.ReadAllBytes(enginePath))).ToLowerInvariant(),
    ["character"] = "Defect",
    ["ascension"] = 10,
    ["multiplayer_constraint"] = runView.CardMultiplayerConstraint.ToString(),
    ["count"] = rows.Count,
    ["cards"] = rows,
};
Console.WriteLine(JsonSerializer.Serialize(result, new JsonSerializerOptions { WriteIndented = true }));
