# -*- coding:utf-8 -*-
"""The MIT License (MIT)
Copyright (c) 2016 Cahyo Primawidodo

Permission is hereby granted, free of charge, to any person obtaining a copy of this software and associated
documentation files (the "Software"), to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense, and/or sell copies of the Software, and
to permit persons to whom the Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all copies or substantial portions of
the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED, INCLUDING BUT NOT LIMITED TO
THE WARRANTIES OF MERCHANTABILITY, FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER LIABILITY, WHETHER IN AN ACTION OF CONTRACT,
TORT OR OTHERWISE, ARISING FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
THE SOFTWARE."""

import io
import struct
import logging
import re
import math
import gzip
from stdf.stdf_type_V4_2007_1 import TYPE


class Reader:
    HEADER_SIZE = 4

    def __init__(self):
        self.log = logging.getLogger(self.__class__.__name__)
        self.STDF_TYPE = {}
        self.STDF_IO = io.BytesIO(b'')
        self.REC_NAME = {}
        self.FMT_MAP = {}
        self.e = '<'

        self.body_start = 0

        self._load_byte_fmt_mapping()
        self._load_stdf_type()

        self.read_rec_list = False

    def _load_stdf_type(self):

        # if json_file is None:
        #     here = path.abspath(path.dirname(__file__))
        #     input_file = path.join(here, 'stdf_v4.json')
        # else:
        #     input_file = json_file
        #
        # self.log.info('loading STDF configuration file = {}'.format(input_file))
        # with open(input_file) as fp:
        self.STDF_TYPE = TYPE # json.load(fp)

        for k, v in self.STDF_TYPE.items():
            typ_sub = (v['rec_typ'], v['rec_sub'])
            self.REC_NAME[typ_sub] = k

    def _load_byte_fmt_mapping(self):
        self.FMT_MAP = {
            "U1": "B",
            "U2": "H",
            "U4": "I",
            "U8": "Q",
            "I1": "b",
            "I2": "h",
            "I4": "i",
            "I8": "q",
            "R4": "f",
            "R8": "d",
            "B1": "B",
            "C1": "c",
            "N1": "B"
            }

    def load_stdf_file(self, stdf_file):
        self.log.info('opening STDF file = {}'.format(stdf_file))
        if stdf_file.endswith(".std") or stdf_file.endswith(".stdf"):
            with open(stdf_file, mode='rb') as fs:
                self.STDF_IO = io.BytesIO(fs.read())
        elif stdf_file.endswith(".gz"):
            with gzip.open(stdf_file, mode='rb') as fs:
                self.STDF_IO = io.BytesIO(fs.read())

        self.log.info('detecting STDF file size = {}'.format(len(self.STDF_IO.getvalue())))

    def auto_detect_endian(self):
        while True:
            header, rec_name = self._read_and_unpack_header()
            if header:
                rec_size, _, _ = header
                body_raw = self._read_body(rec_size)
                rec_name, body = self._unpack_body(header, body_raw)
                if rec_name == 'FAR':
                    self.__set_endian(body['CPU_TYPE'])
                    self.STDF_IO.seek(0)
                    break
            else:
                self.e = '@'
                self.STDF_IO.seek(0)
                break
                # self.__set_endian(body['CPU_TYPE'])

    def read_record_list(self):
        position = self.STDF_IO.tell()
        header, rec_name = self._read_and_unpack_header()

        if header:
            rec_size, _, _ = header
            self.STDF_IO.seek(rec_size + position + 4)
            return rec_name, position
        else:
            return False

    def read_record(self):
        position = self.STDF_IO.tell()
        header, rec_name = self._read_and_unpack_header()

        if header:
            rec_size, _, _ = header
            self.log.debug('BODY start at tell={:0>8}'.format(self.STDF_IO.tell()))
            body_raw = self._read_body(rec_size)
            rec_name, body = self._unpack_body(header, body_raw)
            self.log.debug('BODY end at tell={:0>8}'.format(self.STDF_IO.tell()))
            # To show all the fields
            if len(body) < len(self.STDF_TYPE[rec_name]['body']):
                for field, val in self.STDF_TYPE[rec_name]['body']:
                    if field in body:
                        pass
                    else:
                        body[field] = 'N/A'
                pass
            # if rec_name == 'FAR':
            #     self.__set_endian(body['CPU_TYPE'])

            return rec_name, header, body

        else:
            self.log.info('closing STDF_IO at tell={:0>8}'.format(self.STDF_IO.tell()))
            self.STDF_IO.close()
            return False

    def _read_and_unpack_header(self):
        header_raw = self.STDF_IO.read(self.HEADER_SIZE)

        header = False
        rec_name = ''
        if header_raw:
            header = struct.unpack(self.e + 'HBB', header_raw)
            rec_name = self.REC_NAME.setdefault((header[1], header[2]), 'UNK')
            self.log.debug('len={:0>3}, rec={}'.format(header[0], rec_name))

        return header, rec_name

    def _read_body(self, rec_size):
        self.body_start = self.STDF_IO.tell()
        body_raw = io.BytesIO(self.STDF_IO.read(rec_size))
        # assert len(body_raw.getvalue()) == rec_size
        return body_raw

    def _unpack_body(self, header, body_raw):
        rec_len, rec_typ, rec_sub = header
        typ_sub = (rec_typ, rec_sub)
        rec_name = self.REC_NAME.setdefault(typ_sub, 'UNK')
        max_tell = rec_len
        odd_nibble = True

        body = {}
        if rec_name in self.STDF_TYPE:
            for field, fmt_raw in self.STDF_TYPE[rec_name]['body']:
                self.log.debug('field={}, fmt_raw={}'.format(field, fmt_raw))

                if fmt_raw == 'N1' and not odd_nibble:
                    pass
                elif body_raw.tell() >= max_tell:
                    break

                array_data = []
                if fmt_raw.startswith('K'):
                    mo = re.match('^K([0xn])(\w{2})', fmt_raw)
                    n = self.__get_multiplier(rec_name, field, body)
                    fmt_act = mo.group(2)

                    for i in range(n):
                        data, odd_nibble = self.__get_data(fmt_act, body_raw, odd_nibble)
                        array_data.append(data)

                    body[field] = array_data
                    odd_nibble = True

                elif fmt_raw.startswith('V'):
                    vn_map = ['B0', 'U1', 'U2', 'U4', 'I1', 'I2',
                              'I4', 'R4', 'R8', '', 'Cn', 'Bn', 'Dn', 'N1']
                    tmp = body_raw.read(2)
                    n, = struct.unpack(self.e + 'H', tmp)

                    for i in range(n):
                        tmp = body_raw.read(1)
                        idx, = struct.unpack(self.e + 'B', tmp)
                        # add if to judge whether the field type is valid
                        if idx < len(vn_map):
                            fmt_vn = vn_map[idx]

                            data, odd_nibble = self.__get_data(fmt_vn, body_raw, odd_nibble)
                            array_data.append(data)

                    body[field] = array_data
                    odd_nibble = True

                else:
                    body[field], odd_nibble = self.__get_data(fmt_raw, body_raw, odd_nibble)

        else:
            self.log.warn('record name={} ({}, {}), not found in self.STDF_TYPE'.format(rec_name, rec_typ, rec_sub))

        body_raw.close()
        return rec_name, body

    def __get_data(self, fmt_act, body_raw, odd_nibble):
        data = '' #0
        if fmt_act == 'N1':
            if odd_nibble:
                nibble, = struct.unpack(self.e + 'B', body_raw.read(1))
                _, data = nibble >> 4, nibble & 0xF
                odd_nibble = False
            else:
                body_raw.seek(-1, 1)
                nibble, = struct.unpack(self.e + 'B', body_raw.read(1))
                data, _ = nibble >> 4, nibble & 0xF
                odd_nibble = True
        else:
            fmt, buf = self.__get_format_and_buffer(fmt_act, body_raw)

            if fmt:
                try:
                    d = struct.unpack(self.e + fmt, buf)
                except struct.error:
                    fmt = str(len(buf)) + fmt[-1]
                    d = struct.unpack(self.e + fmt, buf)
                data = d[0] if len(d) == 1 else d
            odd_nibble = True

        return data, odd_nibble

    def __get_format_and_buffer(self, fmt_raw, body_raw):
        fmt = self.__get_format(fmt_raw, body_raw)
        if fmt:
            size = struct.calcsize(fmt)
            buf = body_raw.read(size)
            self.log.debug('fmt={}, buf={}'.format(fmt, buf))
            return fmt, buf
        else:
            return 0, 0

    def __get_format(self, fmt_raw, body_raw):
        self.log.debug('fmt_raw={}, body_raw={}'.format(fmt_raw, body_raw))

        if fmt_raw in self.FMT_MAP:
            return self.FMT_MAP[fmt_raw]

        elif fmt_raw == 'Sn':
            buf = body_raw.read(2)
            n, = struct.unpack(self.e + 'H', buf)
            posfix = 's'

        elif fmt_raw == 'Cn':
            buf = body_raw.read(1)
            if buf != b'':
                n, = struct.unpack(self.e + 'B', buf)
            else:
                n = 0
            posfix = 's'

        elif fmt_raw == 'Bn':
            buf = body_raw.read(1)
            n, = struct.unpack(self.e + 'B', buf)
            posfix = 'B'

        elif fmt_raw == 'Dn':
            buf = body_raw.read(2)
            h, = struct.unpack(self.e + 'H', buf)
            n = math.ceil(h/8)
            posfix = 'B'
        else:
            raise ValueError(fmt_raw, body_raw.tell(), body_raw.__sizeof__())

        return str(n) + posfix if n else ''

    def __set_endian(self, cpu_type):
        if cpu_type == 1:
            self.e = '>'
        elif cpu_type == 2:
            self.e = '<'
        else:
            self.log.critical('Value of FAR: CPU_TYPE is not 1 or 2. Invalid endian.')
            raise IOError(cpu_type)

    @staticmethod
    def __get_multiplier(rec_name, field, body):

        if rec_name == 'SDR':
            if field == 'SITE_NUM':
                return body['SITE_CNT']  # SDR (1, 80)
        if rec_name == 'PGR':
            if field == 'PMR_INDX':
                return body['INDX_CNT']  # PGR (1, 62)
        if rec_name == 'PLR':
            if field in ['GRP_INDX', 'GRP_MODE', 'GRP_RADX', 'PGM_CHAR', 'RTN_CHAR', 'PGM_CHAL', 'RTN_CHAL']:
                return body['GRP_CNT']  # PLR (1, 63)
        if rec_name == 'FTR':
            if field in ['RTN_INDX', 'RTN_STAT']:
                return body['RTN_ICNT']  # FTR (15, 20)
            elif field in ['PGM_INDX', 'PGM_STAT']:
                return body['PGM_ICNT']  # FTR (15, 20)
        if rec_name == 'MPR':
            if field in ['RTN_STAT', 'RTN_INDX']:
                return body['RTN_ICNT']  # MPR (15, 15)

            elif field in ['RTN_RSLT']:
                return body['RSLT_CNT']  # MPR (15, 15)
        if rec_name == 'VUR':
            if field in ['UPD_NAM']:
                return body['UPD_CNT']  # VUR (0, 30)
        if rec_name == 'PSR':
            if field in ["PAT_BGN", "PAT_END", "PAT_FILE", "PAT_LBL", "FILE_UID", "ATPG_DSC", "SRC_ID"]:
                return body["LOCP_CNT"]  # PSR (1, 90)
        if rec_name == 'NMR':
            if field in ["PMR_INDX", "ATPG_NAM"]:
                return body["LOCM_CNT"]  # NMR (1, 91)
        if rec_name == 'SSR':
            if field in ["CHN_LIST"]:
                return body["CHN_CNT"]  # SSR (1, 93)
        if rec_name == 'CDR':
            if field in ["M_CLKS"]:
                return body["MSTR_CNT"]  # CDR (1, 94)
            elif field in ["S_CLKS"]:
                return body["SLAV_CNT"]  # CDR (1, 94)
            elif field in ["CELL_LST"]:
                return body["LST_CNT"]  # CDR (1, 94)
        if rec_name == 'STR':
            if field in ['LIM_INDX', 'LIM_SPEC']:
                return body["LIM_CNT"]  # STR
            elif field in ['COND_LST']:
                return body["COND_CNT"]  # STR
            elif field in ['CYC_OFST']:
                return body["CYCO_CNT"]  # STR
            elif field in ['PMR_INDX']:
                return body["PMR_CNT"]  # STR
            elif field in ['CHN_NUM']:
                return body["CHN_CNT"]  # STR
            elif field in ['EXP_DATA']:
                return body["EXP_CNT"]  # STR
            elif field in ['CAP_DATA']:
                return body["CAP_CNT"]  # STR
            elif field in ['NEW_DATA']:
                return body["NEW_CNT"]  # STR
            elif field in ['PAT_NUM']:
                return body["PAT_CNT"]  # STR
            elif field in ['BIT_POS']:
                return body["BPOS_CNT"]  # STR
            elif field in ['USR1']:
                return body["USR1_CNT"]  # STR
            elif field in ['USR2']:
                return body["USR2_CNT"]  # STR
            elif field in ['USR3']:
                return body["USR3_CNT"]  # STR
            elif field in ['USER_TXT']:
                return body["TXT_CNT"]  # STR

        else:
            raise ValueError

    def __iter__(self):
        self.auto_detect_endian()
        return self

    def __next__(self):
        if self.read_rec_list:
            r = self.read_record_list()
        else:
            r = self.read_record()
        if r:
            return r
        else:
            raise StopIteration
