terraform {
  required_providers {
    oci = { source = "oracle/oci", version = ">= 5.0" }
  }
}

variable "tenancy_ocid" {}
variable "compartment_ocid" {}
variable "availability_domain" {}
variable "ssh_public_key" {}
variable "shape_ocpus" { default = 2 }
variable "shape_memory_gbs" { default = 12 }

resource "oci_core_vcn" "vpn" {
  compartment_id = var.compartment_ocid
  cidr_block     = "10.0.0.0/16"
  display_name   = "filtervpn-vcn"
  dns_label      = "filtervpn"
}

resource "oci_core_internet_gateway" "igw" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.vpn.id
  display_name   = "filtervpn-igw"
  enabled        = true
}

resource "oci_core_route_table" "rt" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.vpn.id
  display_name   = "filtervpn-rt"
  route_rules {
    destination       = "0.0.0.0/0"
    network_entity_id = oci_core_internet_gateway.igw.id
  }
}

resource "oci_core_security_list" "sl" {
  compartment_id = var.compartment_ocid
  vcn_id         = oci_core_vcn.vpn.id
  display_name   = "filtervpn-sl"

  egress_security_rules {
    destination = "0.0.0.0/0"
    protocol    = "all"
  }

  ingress_security_rules { # SSH (tighten source in prod)
    source   = "0.0.0.0/0"
    protocol = "6"
    tcp_options { min = 22 max = 22 }
  }
  ingress_security_rules { # WireGuard
    source   = "0.0.0.0/0"
    protocol = "17"
    udp_options { min = 51820 max = 51820 }
  }
  ingress_security_rules { # Portal HTTPS
    source   = "0.0.0.0/0"
    protocol = "6"
    tcp_options { min = 443 max = 443 }
  }
}

resource "oci_core_subnet" "nodes" {
  compartment_id    = var.compartment_ocid
  vcn_id            = oci_core_vcn.vpn.id
  cidr_block        = "10.0.1.0/24"
  display_name      = "filtervpn-nodes"
  route_table_id    = oci_core_route_table.rt.id
  security_list_ids = [oci_core_security_list.sl.id]
}

resource "oci_core_instance" "vpn" {
  compartment_id      = var.compartment_ocid
  availability_domain = var.availability_domain
  display_name        = "filtervpn-a1"
  shape               = "VM.Standard.A1.Flex"

  shape_config {
    ocpus         = var.shape_ocpus
    memory_in_gbs = var.shape_memory_gbs
  }

  source_details {
    source_type = "image"
    # Ubuntu 24.04 Minimal aarch64 — replace with region-specific OCID
    source_id = "ocid1.image.oc1..ubuntu-24.04-aarch64"
  }

  create_vnic_details {
    subnet_id        = oci_core_subnet.nodes.id
    assign_public_ip = true
  }

  metadata = {
    ssh_authorized_keys = var.ssh_public_key
    user_data           = base64encode(file("${path.module}/../cloud-init.yaml"))
  }
}

output "public_ip" {
  value = oci_core_instance.vpn.public_ip
}
