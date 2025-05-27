import sys
from PyQt6 import QtWidgets, QtCore
from PyQt6.QtWidgets import QMessageBox
from PyQt6.QtCore import QTimer, QDateTime
from ui_mainwindow import Ui_MainWindow
from influxdb_client import InfluxDBClient
from influxdb_client.client.write_api import SYNCHRONOUS
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import datetime
import pytz
import mplcursors

class MonitoringApp(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # InfluxDB Configuration
        self.influx_url = "http://localhost:8086"
        self.influx_org = "INSTITUT TEKNOLOGI SEPULUH NOPEMBER"
        self.influx_token = "oNEA7ExQ-JAaR3zVhfVbbAlAhc4AkcwMUv-QY_8MAqXLX-Dq5jRUFyMtla-Ag92i-GaJcnWyYQ0yX4UezJ3raA=="
        self.influx_bucket = "SHT20"

        # Initialize variables
        self.client = None
        self.query_api = None
        self.timer = QTimer()
        self.update_interval = 10000  # 10 seconds

        # For storing line references
        self.temp_line = None
        self.humidity_line = None
        self.temp_cursor = None
        self.humidity_cursor = None

        # Setup UI
        self.setup_ui()

        # Connect signals
        self.startButton.clicked.connect(self.start_monitoring)
        self.stopButton.clicked.connect(self.stop_monitoring)

        # Initially disable stop button
        self.stopButton.setEnabled(False)

    def setup_ui(self):
        self.setup_charts()

    def setup_charts(self):
        self.temp_figure = Figure()
        self.temp_canvas = FigureCanvas(self.temp_figure)
        self.temp_ax = self.temp_figure.add_subplot(111)
        self.temp_ax.set_title('Temperature (°C) vs Time')
        self.temp_ax.set_xlabel('Time (WIB)')
        self.temp_ax.set_ylabel('Temperature (°C)')
        self.temp_ax.grid(True)
        temp_toolbar = NavigationToolbar(self.temp_canvas, self)
        temp_layout = QtWidgets.QVBoxLayout()
        temp_layout.addWidget(temp_toolbar)
        temp_layout.addWidget(self.temp_canvas)
        self.temperatureChartView.setLayout(temp_layout)

        self.humidity_figure = Figure()
        self.humidity_canvas = FigureCanvas(self.humidity_figure)
        self.humidity_ax = self.humidity_figure.add_subplot(111)
        self.humidity_ax.set_title('Humidity (%) vs Time')
        self.humidity_ax.set_xlabel('Time (WIB)')
        self.humidity_ax.set_ylabel('Humidity (%)')
        self.humidity_ax.grid(True)
        humidity_toolbar = NavigationToolbar(self.humidity_canvas, self)
        humidity_layout = QtWidgets.QVBoxLayout()
        humidity_layout.addWidget(humidity_toolbar)
        humidity_layout.addWidget(self.humidity_canvas)
        self.humidityChartView.setLayout(humidity_layout)

    def start_monitoring(self):
        try:
            self.client = InfluxDBClient(
                url=self.influx_url,
                token=self.influx_token,
                org=self.influx_org,
                timeout=30_000
            )
            self.query_api = self.client.query_api()

            try:
                health = self.client.health()
                if health.status == "pass":
                    self.statusLabel.setText("STATUS: Connected to InfluxDB ✔")
                else:
                    self.statusLabel.setText("STATUS: Connection Issue ⚠")
                    QMessageBox.warning(self, "Warning", f"InfluxDB connection issue: {health.message}")
                    return
            except Exception as health_error:
                self.statusLabel.setText("STATUS: Connection Health Check Failed ❌")
                QMessageBox.warning(self, "Warning", f"Could not check InfluxDB health: {str(health_error)}")
                return

            self.startButton.setEnabled(False)
            self.stopButton.setEnabled(True)
            self.timer.timeout.connect(self.update_data)
            self.timer.start(self.update_interval)
            self.update_data()

        except Exception as e:
            self.statusLabel.setText("STATUS: Connection Failed ❌")
            QMessageBox.critical(self, "Error", f"Failed to connect to InfluxDB: {str(e)}")
            if self.client:
                self.client.close()
            self.client = None
            self.query_api = None

    def stop_monitoring(self):
        self.timer.stop()
        if self.client:
            self.client.close()
            self.client = None
            self.query_api = None

        self.statusLabel.setText("STATUS: Disconnected ⛔")
        self.startButton.setEnabled(True)
        self.stopButton.setEnabled(False)
        QMessageBox.information(self, "Info", "Monitoring stopped")

    def update_data(self):
        if not self.query_api:
            self.statusLabel.setText("STATUS: No Query API ❌")
            QMessageBox.warning(self, "Warning", "Query API not initialized")
            return

        try:
            query = f'''
            from(bucket: "{self.influx_bucket}")
              |> range(start: -1h)
              |> filter(fn: (r) => r["_measurement"] == "environment_monitoring")
              |> filter(fn: (r) => r["_field"] == "humidity_percent" or r["_field"] == "temperature_celsius")
              |> filter(fn: (r) => r["location"] == "Gudang Fermentasi 1")
              |> filter(fn: (r) => r["process_stage"] == "Fermentasi")
              |> filter(fn: (r) => r["sensor_id"] == "SHT20-PascaPanen-001")
              |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
              |> yield(name: "mean")
            '''

            try:
                result = self.query_api.query(query)
            except Exception as query_error:
                self.statusLabel.setText("STATUS: Query Error ⚠")
                QMessageBox.warning(self, "Query Error", f"Failed to execute query: {str(query_error)}")
                return

            temp_data = []
            humidity_data = []
            temp_times = []
            humidity_times = []

            for table in result:
                for record in table.records:
                    if record.get_field() == "temperature_celsius":
                        temp_data.append(record.get_value())
                        temp_times.append(record.get_time())
                    elif record.get_field() == "humidity_percent":
                        humidity_data.append(record.get_value())
                        humidity_times.append(record.get_time())

                    if not self.locationLabel.text().startswith("LOCATION:"):
                        self.locationLabel.setText(f"LOCATION: {record.values.get('location', 'N/A')}")
                        self.processStageLabel.setText(f"PROSES: {record.values.get('process_stage', 'N/A')}")
                        self.sensorIdLabel.setText(f"SENSOR ID: {record.values.get('sensor_id', 'N/A')}")

            if temp_data and temp_times:
                self.update_chart(self.temp_ax, self.temp_canvas, temp_times, temp_data, 'Temperature (°C)')
            if humidity_data and humidity_times:
                self.update_chart(self.humidity_ax, self.humidity_canvas, humidity_times, humidity_data, 'Humidity (%)')

            now = QDateTime.currentDateTime()
            self.updateLabel.setText(f"Last Updated: {now.toString('dd MMMM yyyy - hh:mm:ss')}")

        except Exception as e:
            self.statusLabel.setText("STATUS: Update Error ⚠")
            QMessageBox.warning(self, "Error", f"Error updating data: {str(e)}")

    def update_chart(self, ax, canvas, times, values, title):
        try:
            ax.clear()
            local_tz = pytz.timezone('Asia/Jakarta')
            local_times = [t.astimezone(local_tz) for t in times]
            line, = ax.plot(local_times, values, 'b-')
            if title == 'Temperature (°C)':
                if self.temp_cursor:
                    self.temp_cursor.remove()
                self.temp_line = line
            else:
                if self.humidity_cursor:
                    self.humidity_cursor.remove()
                self.humidity_line = line
            ax.set_title(title)
            ax.set_xlabel('Time (WIB)')
            ax.set_ylabel(title.split(' ')[0])
            ax.grid(True)
            ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%H:%M:%S', tz=local_tz))
            plt.setp(ax.get_xticklabels(), rotation=45)
            formatted_times = [t.strftime('%Y-%m-%d %H:%M:%S') for t in local_times]
            if title == 'Temperature (°C)':
                self.temp_cursor = mplcursors.cursor(line, hover=True)
                def on_add_temp(sel):
                    idx = sel.target.index
                    sel.annotation.set_text(
                        f"{title.split(' ')[0]}: {values[idx]:.2f}\nTime: {formatted_times[idx]}"
                    )
                self.temp_cursor.connect("add", on_add_temp)
            else:
                self.humidity_cursor = mplcursors.cursor(line, hover=True)
                def on_add_humidity(sel):
                    idx = sel.target.index
                    sel.annotation.set_text(
                        f"{title.split(' ')[0]}: {values[idx]:.2f}\nTime: {formatted_times[idx]}"
                    )
                self.humidity_cursor.connect("add", on_add_humidity)
            canvas.draw()

        except Exception as e:
            QMessageBox.warning(self, "Chart Error", f"Error updating chart: {str(e)}")

def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MonitoringApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()