import sys
from PyQt6 import QtWidgets, QtCore
from PyQt6.QtWidgets import QMessageBox, QFileDialog
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
import pandas as pd

class MonitoringApp(QtWidgets.QMainWindow, Ui_MainWindow):
    def __init__(self):
        super().__init__()
        self.setupUi(self)

        # Konfigurasi InfluxDB
        self.influx_url = "http://localhost:8086"
        self.influx_org = "INSTITUT TEKNOLOGI SEPULUH NOPEMBER"
        self.influx_token = "oNEA7ExQ-JAaR3zVhfVbbAlAhc4AkcwMUv-QY_8MAqXLX-Dq5jRUFyMtla-Ag92i-GaJcnWyYQ0yX4UezJ3raA=="
        self.influx_bucket = "SHT20"

        # Inisialisasi variabel
        self.client = None
        self.query_api = None
        self.timer = QTimer()
        self.update_interval = 10000  # 10 detik
        self.all_data = pd.DataFrame()  # Untuk menyimpan semua data

        # Untuk menyimpan referensi garis chart
        self.temp_line = None
        self.humidity_line = None
        self.temp_cursor = None
        self.humidity_cursor = None

        # Setup UI
        self.setup_ui()

        # Hubungkan signal
        self.startButton.clicked.connect(self.start_monitoring)
        self.stopButton.clicked.connect(self.stop_monitoring)

        # Tambahkan tombol ekspor untuk Tab 2
        self.exportButton = QtWidgets.QPushButton(self.tab_2)
        self.exportButton.setGeometry(QtCore.QRect(1400, 30, 161, 31))
        self.exportButton.setText("Ekspor ke Excel")
        self.exportButton.clicked.connect(self.export_to_excel)

        # Tambahkan tombol refresh untuk Tab 2
        self.refreshButton = QtWidgets.QPushButton(self.tab_2)
        self.refreshButton.setGeometry(QtCore.QRect(1200, 30, 161, 31))
        self.refreshButton.setText("Refresh Data")
        self.refreshButton.clicked.connect(self.refresh_table)

        # Awalnya nonaktifkan tombol stop
        self.stopButton.setEnabled(False)

    def setup_ui(self):
        self.setup_charts()
        self.setup_table()

    def setup_charts(self):
        """Menyiapkan grafik untuk Tab 1"""
        self.temp_figure = Figure()
        self.temp_canvas = FigureCanvas(self.temp_figure)
        self.temp_ax = self.temp_figure.add_subplot(111)
        self.temp_ax.set_title('Suhu (°C) vs Waktu')
        self.temp_ax.set_xlabel('Waktu (WIB)')
        self.temp_ax.set_ylabel('Suhu (°C)')
        self.temp_ax.grid(True)
        temp_toolbar = NavigationToolbar(self.temp_canvas, self)
        temp_layout = QtWidgets.QVBoxLayout()
        temp_layout.addWidget(temp_toolbar)
        temp_layout.addWidget(self.temp_canvas)
        self.temperatureChartView.setLayout(temp_layout)

        self.humidity_figure = Figure()
        self.humidity_canvas = FigureCanvas(self.humidity_figure)
        self.humidity_ax = self.humidity_figure.add_subplot(111)
        self.humidity_ax.set_title('Kelembaban (%) vs Waktu')
        self.humidity_ax.set_xlabel('Waktu (WIB)')
        self.humidity_ax.set_ylabel('Kelembaban (%)')
        self.humidity_ax.grid(True)
        humidity_toolbar = NavigationToolbar(self.humidity_canvas, self)
        humidity_layout = QtWidgets.QVBoxLayout()
        humidity_layout.addWidget(humidity_toolbar)
        humidity_layout.addWidget(self.humidity_canvas)
        self.humidityChartView.setLayout(humidity_layout)

    def setup_table(self):
        """Menyiapkan tabel untuk Tab 2"""
        self.tableWidget.setColumnCount(5)
        self.tableWidget.setHorizontalHeaderLabels([
            "Waktu", 
            "Lokasi", 
            "Tahap Proses", 
            "Suhu (°C)", 
            "Kelembaban (%)"
        ])
        self.tableWidget.horizontalHeader().setSectionResizeMode(QtWidgets.QHeaderView.ResizeMode.Stretch)
        self.tableWidget.setSortingEnabled(True)

    def start_monitoring(self):
        """Memulai monitoring data"""
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
                    self.statusLabel.setText("STATUS: Terhubung ke InfluxDB ✔")
                else:
                    self.statusLabel.setText("STATUS: Masalah Koneksi ⚠")
                    QMessageBox.warning(self, "Peringatan", f"Masalah koneksi InfluxDB: {health.message}")
                    return
            except Exception as health_error:
                self.statusLabel.setText("STATUS: Gagal Cek Kesehatan ❌")
                QMessageBox.warning(self, "Peringatan", f"Tidak bisa cek kesehatan InfluxDB: {str(health_error)}")
                return

            self.startButton.setEnabled(False)
            self.stopButton.setEnabled(True)
            self.timer.timeout.connect(self.update_data)
            self.timer.start(self.update_interval)
            self.update_data()

        except Exception as e:
            self.statusLabel.setText("STATUS: Gagal Koneksi ❌")
            QMessageBox.critical(self, "Error", f"Gagal terhubung ke InfluxDB: {str(e)}")
            if self.client:
                self.client.close()
            self.client = None
            self.query_api = None

    def stop_monitoring(self):
        """Menghentikan monitoring"""
        self.timer.stop()
        if self.client:
            self.client.close()
            self.client = None
            self.query_api = None

        self.statusLabel.setText("STATUS: Terputus ⛔")
        self.startButton.setEnabled(True)
        self.stopButton.setEnabled(False)
        QMessageBox.information(self, "Info", "Monitoring dihentikan")

    def update_data(self):
        """Memperbarui data dari InfluxDB"""
        if not self.query_api:
            self.statusLabel.setText("STATUS: Query API tidak tersedia ❌")
            QMessageBox.warning(self, "Peringatan", "Query API belum diinisialisasi")
            return

        try:
            query = f'''
            from(bucket: "{self.influx_bucket}")
              |> range(start: -24h) 
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
                self.statusLabel.setText("STATUS: Error Query ⚠")
                QMessageBox.warning(self, "Error Query", f"Gagal menjalankan query: {str(query_error)}")
                return

            temp_data = []
            humidity_data = []
            temp_times = []
            humidity_times = []
            records_list = []  # Untuk menyimpan data ke tabel

            for table in result:
                for record in table.records:
                    if record.get_field() == "temperature_celsius":
                        temp_data.append(record.get_value())
                        temp_times.append(record.get_time())
                    elif record.get_field() == "humidity_percent":
                        humidity_data.append(record.get_value())
                        humidity_times.append(record.get_time())

                    if not self.locationLabel.text().startswith("LOCATION:"):
                        self.locationLabel.setText(f"LOKASI: {record.values.get('location', 'N/A')}")
                        self.processStageLabel.setText(f"PROSES: {record.values.get('process_stage', 'N/A')}")
                        self.sensorIdLabel.setText(f"SENSOR ID: {record.values.get('sensor_id', 'N/A')}")

                    # Simpan data untuk tabel
                    records_list.append({
                        'time': record.get_time(),
                        'location': record.values.get('location', 'N/A'),
                        'process_stage': record.values.get('process_stage', 'N/A'),
                        'field': record.get_field(),
                        'value': record.get_value()
                    })

            if temp_data and temp_times:
                self.update_chart(self.temp_ax, self.temp_canvas, temp_times, temp_data, 'Suhu (°C)')
            if humidity_data and humidity_times:
                self.update_chart(self.humidity_ax, self.humidity_canvas, humidity_times, humidity_data, 'Kelembaban (%)')

            # Perbarui data tabel
            if records_list:
                self.update_data_table(records_list)

            now = QDateTime.currentDateTime()
            self.updateLabel.setText(f"Terakhir Diperbarui: {now.toString('dd MMMM yyyy - hh:mm:ss')}")

        except Exception as e:
            self.statusLabel.setText("STATUS: Error Pembaruan ⚠")
            QMessageBox.warning(self, "Error", f"Error memperbarui data: {str(e)}")

    def update_chart(self, ax, canvas, times, values, title):
        """Memperbarui grafik dengan data baru"""
        try:
            ax.clear()
            local_tz = pytz.timezone('Asia/Jakarta')
            local_times = [t.astimezone(local_tz) for t in times]
            line, = ax.plot(local_times, values, 'b-')
            if title == 'Suhu (°C)':
                if self.temp_cursor:
                    self.temp_cursor.remove()
                self.temp_line = line
            else:
                if self.humidity_cursor:
                    self.humidity_cursor.remove()
                self.humidity_line = line
            ax.set_title(title)
            ax.set_xlabel('Waktu (WIB)')
            ax.set_ylabel(title.split(' ')[0])
            ax.grid(True)
            ax.xaxis.set_major_formatter(plt.matplotlib.dates.DateFormatter('%H:%M:%S', tz=local_tz))
            plt.setp(ax.get_xticklabels(), rotation=45)
            formatted_times = [t.strftime('%Y-%m-%d %H:%M:%S') for t in local_times]
            if title == 'Suhu (°C)':
                self.temp_cursor = mplcursors.cursor(line, hover=True)
                def on_add_temp(sel):
                    idx = sel.target.index
                    sel.annotation.set_text(
                        f"{title.split(' ')[0]}: {values[idx]:.2f}\nWaktu: {formatted_times[idx]}"
                    )
                self.temp_cursor.connect("add", on_add_temp)
            else:
                self.humidity_cursor = mplcursors.cursor(line, hover=True)
                def on_add_humidity(sel):
                    idx = sel.target.index
                    sel.annotation.set_text(
                        f"{title.split(' ')[0]}: {values[idx]:.2f}\nWaktu: {formatted_times[idx]}"
                    )
                self.humidity_cursor.connect("add", on_add_humidity)
            canvas.draw()

        except Exception as e:
            QMessageBox.warning(self, "Error Grafik", f"Error memperbarui grafik: {str(e)}")

    def update_data_table(self, new_records):
        """Memperbarui tabel dengan data baru"""
        try:
            # Konversi records ke DataFrame
            new_df = pd.DataFrame(new_records)
            
            # Gabungkan dengan data yang sudah ada
            if not self.all_data.empty:
                # Gabungkan dan hapus duplikat
                self.all_data = pd.concat([self.all_data, new_df]).drop_duplicates(
                    subset=['time', 'field'], 
                    keep='last'
                )
            else:
                self.all_data = new_df
            
            # Pivot data untuk tampilan tabel
            df_pivot = self.all_data.pivot_table(
                index=['time', 'location', 'process_stage'], 
                columns='field', 
                values='value'
            ).reset_index()
            
            # Konversi waktu ke timezone lokal
            local_tz = pytz.timezone('Asia/Jakarta')
            df_pivot['time'] = pd.to_datetime(df_pivot['time']).dt.tz_convert(local_tz)
            
            # Format waktu untuk tampilan
            df_pivot['time_str'] = df_pivot['time'].dt.strftime('%Y-%m-%d %H:%M:%S')
            
            # Simpan data lengkap untuk ekspor
            self.export_data = df_pivot.copy()
            
            # Perbarui tabel
            self.refresh_table()

        except Exception as e:
            QMessageBox.warning(self, "Error Tabel", f"Error memperbarui tabel: {str(e)}")

    def refresh_table(self):
        """Menyegarkan tampilan tabel dengan data terbaru"""
        try:
            if hasattr(self, 'export_data') and not self.export_data.empty:
                # Nonaktifkan sorting sementara untuk performa
                self.tableWidget.setSortingEnabled(False)
                
                # Set jumlah baris sesuai data
                self.tableWidget.setRowCount(len(self.export_data))
                
                # Isi tabel dengan data
                for row_idx, row in self.export_data.iterrows():
                    self.tableWidget.setItem(row_idx, 0, QtWidgets.QTableWidgetItem(row['time_str']))
                    self.tableWidget.setItem(row_idx, 1, QtWidgets.QTableWidgetItem(row['location']))
                    self.tableWidget.setItem(row_idx, 2, QtWidgets.QTableWidgetItem(row['process_stage']))
                    self.tableWidget.setItem(row_idx, 3, QtWidgets.QTableWidgetItem(f"{row.get('temperature_celsius', 'N/A'):.2f}"))
                    self.tableWidget.setItem(row_idx, 4, QtWidgets.QTableWidgetItem(f"{row.get('humidity_percent', 'N/A'):.2f}"))
                
                # Aktifkan kembali sorting
                self.tableWidget.setSortingEnabled(True)
                
        except Exception as e:
            QMessageBox.warning(self, "Error", f"Gagal menyegarkan tabel: {str(e)}")

    def export_to_excel(self):
        """Mengekspor data ke file Excel"""
        if not hasattr(self, 'export_data') or self.export_data.empty:
            QMessageBox.warning(self, "Peringatan", "Tidak ada data untuk diekspor")
            return
            
        try:
            # Gunakan file dialog untuk memilih lokasi penyimpanan
            file_name, _ = QFileDialog.getSaveFileName(
                self, 
                "Simpan File Excel", 
                "", 
                "File Excel (*.xlsx);;Semua File (*)"
            )
            
            if file_name:
                # Pastikan ekstensi .xlsx
                if not file_name.endswith('.xlsx'):
                    file_name += '.xlsx'
                
                # Buat salinan data untuk ekspor
                export_df = self.export_data.copy()
                
                # Konversi kolom waktu ke timezone naive (tanpa timezone)
                if 'time' in export_df.columns:
                    export_df['time'] = export_df['time'].dt.tz_localize(None)
                
                # Siapkan data untuk ekspor
                export_df = export_df[['time', 'location', 'process_stage', 
                                    'temperature_celsius', 'humidity_percent']]
                export_df.columns = ['Waktu', 'Lokasi', 'Tahap Proses', 
                                'Suhu (°C)', 'Kelembaban (%)']
                
                # Ekspor ke Excel
                export_df.to_excel(file_name, index=False)
                QMessageBox.information(self, "Sukses", "Data berhasil diekspor ke Excel")
                
        except Exception as e:
            QMessageBox.warning(self, "Error Ekspor", f"Gagal mengekspor data: {str(e)}")

def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MonitoringApp()
    window.show()
    sys.exit(app.exec())

if __name__ == "__main__":
    main()