using MegaCrit.Sts2.Core.Localization;
using MegaCrit.Sts2.Core.Localization.DynamicVars;

namespace Sts2Headless;

public partial class RunSimulator
{
    /// <summary>
    /// Merge variables which the engine already attached to a public event-option label.
    /// Keep this allow-list narrow: arbitrary engine objects may contain hidden run state and
    /// are neither stable nor safe JSON protocol values.
    /// </summary>
    internal static void MergePublicLocVariables(
        Dictionary<string, object?> destination,
        LocString? locString)
    {
        if (locString == null) return;

        foreach (var (name, sourceValue) in locString.Variables)
        {
            if (TryGetPublicLocVariable(sourceValue, out var value))
                destination[name] = value;
        }
    }

    internal static bool TryGetPublicLocVariable(object? sourceValue, out object? value)
    {
        switch (sourceValue)
        {
            case StringVar stringVar:
                value = stringVar.StringValue;
                return true;
            case DynamicVar dynamicVar:
                // Preserve the bridge's existing event-variable wire format.
                value = (int)dynamicVar.BaseValue;
                return true;
            case string or bool or byte or sbyte or short or ushort or int or uint or long or ulong
                or float or double or decimal:
                value = sourceValue;
                return true;
            case IList<string> strings:
                value = strings.ToArray();
                return true;
            case LocString nested:
                try
                {
                    value = nested.GetFormattedText();
                    return true;
                }
                catch
                {
                    value = null;
                    return false;
                }
            default:
                value = null;
                return false;
        }
    }
}
