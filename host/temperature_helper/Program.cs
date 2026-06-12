using System.Text.Json;
using LibreHardwareMonitor.Hardware;

const string mutexName = @"Local\HW75Dashboard.TemperatureService";
using var mutex = new Mutex(true, mutexName, out bool isFirstInstance);
if (!isFirstInstance)
{
    return;
}

string dataDirectory = Path.Combine(
    Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData),
    "HW75Dashboard");
string outputPath = Path.Combine(dataDirectory, "cpu-temperature.json");
Directory.CreateDirectory(dataDirectory);

var computer = new Computer { IsCpuEnabled = true };
computer.Open();
AppDomain.CurrentDomain.ProcessExit += (_, _) => computer.Close();

while (true)
{
    try
    {
        SensorReading? reading = ReadCpuTemperature(computer);
        if (reading is not null)
        {
            string temporaryPath = outputPath + ".tmp";
            string json = JsonSerializer.Serialize(new
            {
                temperature = (int)Math.Round(reading.Value.Value),
                sensor = reading.Value.Name,
                updated_at = DateTimeOffset.UtcNow.ToUnixTimeSeconds()
            });
            File.WriteAllText(temporaryPath, json);
            File.Move(temporaryPath, outputPath, true);
        }
    }
    catch
    {
        // A transient sensor failure should not stop future samples.
    }

    Thread.Sleep(TimeSpan.FromSeconds(5));
}

static SensorReading? ReadCpuTemperature(Computer computer)
{
    var readings = new List<SensorReading>();
    foreach (IHardware hardware in computer.Hardware)
    {
        hardware.Update();
        CollectTemperatures(hardware, readings);
        foreach (IHardware subHardware in hardware.SubHardware)
        {
            subHardware.Update();
            CollectTemperatures(subHardware, readings);
        }
    }

    string[] preferredNames = ["CPU Package", "Core Max", "Core Average"];
    foreach (string preferredName in preferredNames)
    {
        int index = readings.FindIndex(
            reading => reading.Name.Equals(preferredName, StringComparison.OrdinalIgnoreCase));
        if (index >= 0)
        {
            return readings[index];
        }
    }

    return readings.Count > 0
        ? readings.OrderByDescending(reading => reading.Value).First()
        : null;
}

static void CollectTemperatures(IHardware hardware, List<SensorReading> readings)
{
    foreach (ISensor sensor in hardware.Sensors)
    {
        if (sensor.SensorType == SensorType.Temperature &&
            sensor.Value is float value && value is >= 1 and <= 125)
        {
            readings.Add(new SensorReading(sensor.Name, value));
        }
    }
}

readonly record struct SensorReading(string Name, float Value);
