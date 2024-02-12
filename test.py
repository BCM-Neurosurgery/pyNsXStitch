import numpy as np
from matplotlib import pyplot as plt
from pyNsXStitch.helpers import NsxFile


seconds = 2.0
start_time = 10.0

f = NsxFile(r"D:\Work\DataNet\TestData\lake\blackrock\20240125-144340\20240125-144340-002.ns5")

data = f.getdata(start_time_s=start_time, data_time_s=seconds)
all_elecs = data['data'][0]
for elec_id in all_elecs.shape[0]:
    plt.figure()
    step = 1
    ts_res = f.basic_header['TimeStampResolution']
    one_elec = np.array(all_elecs[elec_id, ::step])
    x = np.array(range(0, all_elecs.shape[1], step)) / ts_res

    elec_info = f.extended_headers[elec_id]
    plt.plot(x, one_elec)
    plt.xlabel('Time (s)')
    plt.title(
        f'{elec_info["ElectrodeLabel"]} '
        f'- Connector {elec_info["ConnectorPin"]} '
        f'- ElecID {elec_info["ElectrodeID"]} '
        )
plt.show()
