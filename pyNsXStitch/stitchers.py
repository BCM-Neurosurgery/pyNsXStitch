from struct import unpack, pack

import numpy as np
from datetime import datetime
from brpylib import NsxFile, NevFile
from brpylib.brpylib import ELEC_ID_DEF, check_elecid, check_dataelecid, NSX_BASIC_HEADER_BYTES_22, \
    NSX_EXT_HEADER_BYTES_22

from pyNsXStitch.streamers import stream_nev_packets, stream_nsx_data


class StitchedNeVFile(object):

    meta_size = 8 + 2
    create_file_loc = 8 + 2*2 + 4*4 + 16
    basic_header_size = create_file_loc + 32 + 256 + 4

    def __init__(self, files_to_stitch, start=None, end=None):
        self.files = files_to_stitch
        self.start_time = start
        self.end_time = end
        self.skip_packet_ids = None

    def get_max_packet_size(self):
        packet_sizes = [NevFile(filename).basic_header['BytesInDataPackets'] for filename in self.files]
        print(packet_sizes)
        return max(packet_sizes)

    def iter_data(self, gui_updater=None):
        """Iterate through all the data packets in a file"""
        max_packet = self.get_max_packet_size()
        if self.start_time is not None and self.end_time is not None:
            duration = self.end_time - self.start_time
        else:
            duration = None

        for file_i, filename in enumerate(self.files):
            nev_file = NevFile(filename)
            for meta, packet_data in stream_nev_packets(nev_file, start=self.start_time, end=self.end_time):
                if gui_updater is not None and duration is not None:
                    elapsed = meta[0] - self.start_time
                    gui_updater(100 * elapsed / duration)
                packet_id = meta[1]
                if self.skip_packet_ids is not None and packet_id in self.skip_packet_ids:
                    # Detect and skip some packets if we were asked to skip packets of this type
                    continue

                # Make sure that all packets from all files are the same size
                n_bytes_to_pad = (max_packet - self.meta_size - len(packet_data))
                padded_packet = packet_data + (b'\x00' * n_bytes_to_pad)
                yield meta, padded_packet

    def write_headers(self, out_file):
        """"""

        # Copy all the headers from the origin file
        origin = NevFile(self.files[0])
        origin.datafile.seek(0, 0)
        out_file.seek(0, 0)
        out_file.write(origin.datafile.read(origin.basic_header['BytesInHeader']))

        # # The only header that we need to update is the Application to Create File
        # old_application = origin.basic_header['CreatingApplication']
        # combo = f'{old_application} + NsXStitcher v0.1'
        # combo_bytes = pack('32s', combo.encode('ANSI'))
        # out_file.seek(self.create_file_loc, 0)
        # out_file.write(combo_bytes)

        # Set the file pointer to the end of the header, so we are ready to write packets
        out_file.seek(origin.basic_header['BytesInHeader'], 0)

    def write(self, out_file, gui_updater=None):

        self.write_headers(out_file)

        # Write all the data packets in order
        for meta, packet in self.iter_data(gui_updater=gui_updater):
            out_file.write(pack('<Q', meta[0]))
            out_file.write(pack('<H', meta[1]))

            out_file.write(packet)


class StitchedNsXFile(object):

    def __init__(self, files_to_stitch, start=None, end=None):

        self.files = files_to_stitch
        self.start_time = start
        self.end_time = end

    def iter_data(self, gui_updater=None):
        """
        Iterator that will loop over all the data packets in all the NsX files

        See helpers.stream_nsx_data for details about how the data is streamed out from each individual file
        """
        duration = self.end_time - self.start_time \
            if self.end_time is not None and self.start_time is not None \
            else None
        for file_i, filename in enumerate(self.files):
            nsx_file = NsxFile(filename)
            streamer = stream_nsx_data(
                nsx_file,
                read_start_time=self.start_time,
                read_end_time=self.end_time
            )
            for meta, data_block in streamer:
                if gui_updater is not None and meta is not None and duration is not None:
                    elapsed = meta[0] - self.start_time
                    gui_updater(100 * elapsed / duration)
                if meta is not None:
                    pass
                yield meta, data_block

    def write_headers(self, out_file):

        # Load an NsX file to pull headers from
        origin = NsxFile(self.files[0])
        origin.datafile.seek(0, 0)

        # Make sure we're writing to hte very start of the new file
        out_file.seek(0, 0)

        # Copy over the headers
        bytes_in_headers = origin.basic_header['BytesInHeader']
        out_file.write(origin.datafile.read(bytes_in_headers))

    def write(self, out_file, gui_updater=None):

        self.write_headers(out_file)

        prev_loop_t = datetime.now()
        durations = []
        for meta, data_block in self.iter_data(gui_updater=gui_updater):

            # Data blocks at the start of a packet have timestamps. Write them back at start
            if meta is not None:
                print(f'Timestamp: {meta[0]}  NPoints:{meta[1]}')
                out_file.write(pack('x'))
                out_file.write(pack('<Q', meta[0]))
                out_file.write(pack('<I', meta[1]))

            out_file.write(data_block)

            loop_end = datetime.now()
            loop_duration = loop_end - prev_loop_t
            durations.append(loop_duration)
            prev_loop_t = datetime.now()

        print(f'Avg block write time {np.mean(durations)}')
